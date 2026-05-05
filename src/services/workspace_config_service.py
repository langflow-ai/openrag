"""DB-backed workspace config — replaces ``config.yaml`` as the source
of truth, with yaml kept as a fallback during the Phase B transition.

Mirrors the existing ``ConfigManager`` API surface
(``load_config`` / ``get_config`` / ``reload_config`` / ``save_config_file``
/ ``update_onboarding_state``) so call sites in the API layer don't need
rewrites. Adds two new helpers (``is_onboarded``, ``get_onboarding_step``)
that the new public ``GET /api/onboarding-status`` endpoint uses.

Phase B (this PR) — read DB first, fall back to yaml; write to BOTH
DB and yaml on every save. Phase C (next release) drops the yaml path.

Kill switch: set OPENRAG_DISABLE_DB_WORKSPACE_CONFIG=true to bypass the
DB entirely and operate exactly like the legacy ConfigManager. Intended
as a fast rollback if anything goes wrong in production.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from config.config_manager import ConfigManager, OpenRAGConfig
from db.repositories import WorkspaceConfigRepo
from utils.encryption import encrypt_secret
from utils.logging_config import get_logger

logger = get_logger(__name__)


_SECTIONS_FROM_CONFIG = ("providers", "knowledge", "agent", "onboarding")


def _kill_switch_on() -> bool:
    return os.getenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", "").lower() in (
        "true", "1", "yes",
    )


class WorkspaceConfigService:
    """Drop-in replacement for the parts of ConfigManager that touch
    persistence. Delegates to the legacy ConfigManager for yaml writes
    and installs a monkey-patch on it so EVERY yaml save/update —
    including legacy call sites in src/api/settings.py — auto-mirrors
    to the SQL workspace_config table fire-and-forget."""

    def __init__(
        self,
        config_manager: ConfigManager,
        session_factory: async_sessionmaker,
    ):
        self._cm = config_manager
        self._session_factory = session_factory
        if not _kill_switch_on():
            self._install_yaml_write_hooks()

    # ------------------------------------------------------------------
    # Auto-mirror hook (covers legacy callers that bypass this service)
    # ------------------------------------------------------------------

    def _install_yaml_write_hooks(self) -> None:
        """Wrap config_manager.save_config_file + update_onboarding_state
        so any successful yaml write schedules an async DB mirror.

        Idempotent — guarded by an `_db_mirror_installed` flag on the
        config_manager instance so re-instantiating the service (e.g.
        in tests) doesn't double-patch.
        """
        cm = self._cm
        if getattr(cm, "_db_mirror_installed", False):
            return

        original_save = cm.save_config_file
        original_update_ob = cm.update_onboarding_state

        def patched_save(config=None, preserve_edited: bool = False) -> bool:
            ok = original_save(config, preserve_edited=preserve_edited)
            if ok:
                self._schedule_mirror()
            return ok

        def patched_update_ob(**kwargs) -> bool:
            ok = original_update_ob(**kwargs)
            if ok:
                self._schedule_mirror()
            return ok

        cm.save_config_file = patched_save  # type: ignore[method-assign]
        cm.update_onboarding_state = patched_update_ob  # type: ignore[method-assign]
        cm._db_mirror_installed = True  # type: ignore[attr-defined]
        logger.info("WorkspaceConfigService: yaml-write → DB mirror hooks installed")

    def _schedule_mirror(self) -> None:
        """Fire-and-forget DB mirror of the current config_manager state.

        Runs as an asyncio Task on whatever loop is currently active
        (uvicorn's request loop in production). Failures are logged but
        never propagate back to the synchronous yaml writer.

        If called from a context with no running loop (e.g. a test that
        invokes save_config_file synchronously), the mirror is skipped —
        the next async-aware caller (load_config / explicit save_config)
        will catch up.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop, no mirror — boot-time migration handles backfill

        async def _do_mirror():
            try:
                await self._mirror_to_db(self._cm.get_config())
            except Exception as exc:  # noqa: BLE001
                logger.warning("DB mirror after yaml save failed", error=str(exc))

        loop.create_task(_do_mirror())

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    async def load_config(self) -> OpenRAGConfig:
        """DB-first read. Falls back to yaml when DB is empty or the
        kill-switch is on. Updates the underlying ConfigManager cache so
        synchronous call sites (``get_openrag_config()``) see the same
        view as DB readers."""
        if _kill_switch_on():
            return self._cm.load_config()

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                rows = await repo.list_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workspace_config DB read failed, falling back to yaml",
                error=str(exc),
            )
            return self._cm.load_config()

        if not rows:
            # No DB rows yet (pre-migration boot or fresh install). Use
            # yaml as authority; the migration will populate the DB on
            # first chance.
            return self._cm.load_config()

        # Build a config_data dict matching what ConfigManager.from_dict
        # expects, then hand off so all the existing decryption /
        # default-merging logic stays in one place.
        merged: dict[str, Any] = {
            "providers": rows.get("providers", {}),
            "knowledge": rows.get("knowledge", {}),
            "agent": rows.get("agent", {}),
            "onboarding": rows.get("onboarding", {}),
            "edited": (rows.get("meta") or {}).get("edited", False),
        }
        config = OpenRAGConfig.from_dict(merged)

        # Keep the legacy in-process cache aligned with the DB so
        # synchronous get_openrag_config() callers see the same data.
        self._cm._config = config
        return config

    async def get_config(self) -> OpenRAGConfig:
        if self._cm._config is not None:
            return self._cm._config
        return await self.load_config()

    async def reload_config(self) -> OpenRAGConfig:
        self._cm._config = None
        return await self.load_config()

    async def is_onboarded(self) -> bool:
        if _kill_switch_on():
            return self._cm.load_config().edited

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                meta = await repo.get_section("meta") or {}
                if "edited" in meta:
                    return bool(meta["edited"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("is_onboarded DB read failed, falling back to yaml", error=str(exc))

        # Fall back to yaml
        return self._cm.load_config().edited

    async def get_onboarding_step(self) -> Optional[Any]:
        """Returns the legacy step indicator — usually an int index from
        the OnboardingState dataclass, sometimes None. Callers should
        treat the value as opaque."""
        if _kill_switch_on():
            return self._cm.load_config().onboarding.current_step

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                ob = await repo.get_section("onboarding") or {}
                if "current_step" in ob:
                    return ob.get("current_step")
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_onboarding_step DB read failed", error=str(exc))

        return self._cm.load_config().onboarding.current_step

    # ------------------------------------------------------------------
    # Write paths (dual-write during Phase B)
    # ------------------------------------------------------------------

    async def save_config(
        self,
        config: Optional[OpenRAGConfig] = None,
        *,
        preserve_edited: bool = False,
        actor_user_id: Optional[str] = None,
    ) -> bool:
        """Write to both yaml and DB. Yaml goes via the patched
        ``config_manager.save_config_file`` (which schedules a
        fire-and-forget DB mirror). For stronger consistency we then
        ALSO await the DB mirror synchronously so callers can rely on
        ``is_onboarded()`` reflecting the new state immediately on
        return. Idempotent upserts so the duplicate write is safe."""
        try:
            ok = self._cm.save_config_file(config, preserve_edited=preserve_edited)
            if not ok:
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("save_config: yaml write failed", error=str(exc))
            return False

        if _kill_switch_on():
            return True

        try:
            await self._mirror_to_db(self._cm.get_config(), actor_user_id=actor_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("save_config: explicit DB mirror failed", error=str(exc))
        return True

    async def update_onboarding_state(
        self,
        actor_user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        try:
            ok = self._cm.update_onboarding_state(**kwargs)
            if not ok:
                return False
        except Exception as exc:  # noqa: BLE001
            logger.error("update_onboarding_state: yaml failed", error=str(exc))
            return False

        if _kill_switch_on():
            return True

        try:
            await self._mirror_to_db(self._cm.get_config(), actor_user_id=actor_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("update_onboarding_state: explicit DB mirror failed", error=str(exc))
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _mirror_to_db(
        self,
        config: OpenRAGConfig,
        *,
        actor_user_id: Optional[str] = None,
    ) -> None:
        """Upsert all sections + meta. Provider api_keys are re-encrypted
        with the JSON envelope so the DB never sees plaintext."""
        config_dict = config.to_dict()

        providers = dict(config_dict.get("providers", {}))
        for prov_name, prov_data in providers.items():
            if isinstance(prov_data, dict) and "api_key" in prov_data and prov_data["api_key"]:
                # Re-encrypt to keep the on-disk and in-DB envelopes in
                # the same shape (encrypt_secret is a no-op when the
                # master key is unset, matching ConfigManager behavior).
                prov_data["api_key"] = encrypt_secret(prov_data["api_key"])
            providers[prov_name] = prov_data

        sections = {
            "providers": providers,
            "knowledge": config_dict.get("knowledge", {}),
            "agent": config_dict.get("agent", {}),
            "onboarding": config_dict.get("onboarding", {}),
            "meta": {"edited": bool(config_dict.get("edited", False))},
        }

        async with self._session_factory() as session:
            repo = WorkspaceConfigRepo(session)
            for section, value in sections.items():
                await repo.upsert(section, value, actor_user_id=actor_user_id)
            await session.commit()
