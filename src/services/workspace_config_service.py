"""DB-backed workspace config — replaces ``config.yaml`` as the source
of truth, with yaml kept as a fallback when storage mode is `hybrid`.

Honors the unified ``OPENRAG_STORAGE_MODE`` flag (see
``src/config/storage_mode.py``):

| Mode             | Reads             | Writes               |
|------------------|-------------------|----------------------|
| db (default)     | DB only           | DB only — yaml ignored, never written |
| hybrid           | DB → yaml fallback| DB + yaml dual-write |
| files            | yaml only         | yaml only            |

Mirrors the existing ``ConfigManager`` API surface (``load_config`` /
``get_config`` / ``reload_config`` / ``save_config_file`` /
``update_onboarding_state``) so call sites in ``src/api/`` don't need
rewrites. Adds two new helpers (``is_onboarded``, ``get_onboarding_step``)
that the new public ``GET /api/onboarding-status`` endpoint uses.

In `hybrid` and `db` modes a one-time monkey-patch on ``config_manager``
intercepts every legacy ``save_config_file`` / ``update_onboarding_state``
call so the DB stays in sync without each call site needing changes.
In `files` mode the patch is not installed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from config.config_manager import ConfigManager, OpenRAGConfig
from config.storage_mode import (
    db_writes_enabled,
    file_writes_enabled,
    get_storage_mode,
)
from db.repositories import WorkspaceConfigRepo
from utils.encryption import encrypt_secret
from utils.logging_config import get_logger

logger = get_logger(__name__)


class WorkspaceConfigService:
    """Drop-in replacement for the parts of ConfigManager that touch
    persistence. Behavior selected by ``OPENRAG_STORAGE_MODE``."""

    def __init__(
        self,
        config_manager: ConfigManager,
        session_factory: async_sessionmaker,
    ):
        self._cm = config_manager
        self._session_factory = session_factory
        # Track in-flight DB-mirror tasks so the lifespan shutdown can
        # await them, and serialize them so rapid double-saves don't
        # race on the DB.
        self._mirror_lock = asyncio.Lock()
        self._pending_mirrors: set[asyncio.Task] = set()
        if db_writes_enabled():
            self._install_yaml_write_hooks()
        logger.info(
            "WorkspaceConfigService initialized",
            storage_mode=get_storage_mode(),
        )

    async def await_pending_mirrors(self) -> None:
        """Block until every pending mirror task has finished.

        Called from the lifespan shutdown handler so we don't drop
        in-flight DB writes when uvicorn cancels remaining tasks.
        """
        if not self._pending_mirrors:
            return
        pending = list(self._pending_mirrors)
        logger.info("awaiting pending DB mirror tasks", count=len(pending))
        await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------
    # Read paths
    # ------------------------------------------------------------------

    async def load_config(self) -> OpenRAGConfig:
        """Mode-aware read.

        - ``files``: yaml only.
        - ``db``: DB only — empty DB returns defaults, yaml is ignored.
        - ``hybrid``: DB-first, yaml fallback when DB is empty.

        Updates the ConfigManager in-process cache so synchronous
        ``get_openrag_config()`` callers see the same data.
        """
        mode = get_storage_mode()
        if mode == "files":
            return self._cm.load_config()

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                rows = await repo.list_all()
        except Exception as exc:  # noqa: BLE001
            if mode == "db":
                logger.error("DB read failed in db mode — returning defaults", error=str(exc))
                return OpenRAGConfig.from_dict({})
            logger.warning(
                "DB read failed, falling back to yaml (hybrid)",
                error=str(exc),
            )
            return self._cm.load_config()

        if not rows:
            if mode == "db":
                # Pre-migration boot in pure-db mode — return defaults.
                # The boot-time migration (config_yaml_to_db_v1) will
                # populate the DB on the next request.
                return OpenRAGConfig.from_dict({})
            return self._cm.load_config()  # hybrid fallback

        merged: dict[str, Any] = {
            "providers": rows.get("providers", {}),
            "knowledge": rows.get("knowledge", {}),
            "agent": rows.get("agent", {}),
            "onboarding": rows.get("onboarding", {}),
            "edited": (rows.get("meta") or {}).get("edited", False),
        }
        config = OpenRAGConfig.from_dict(merged)
        self._cm._config = config
        return config

    async def get_config(self) -> OpenRAGConfig:
        if self._cm._config is not None:
            return self._cm._config
        return await self.load_config()

    async def reload_config(self) -> OpenRAGConfig:
        self._cm._config = None
        return await self.load_config()

    async def hydrate_on_startup(self) -> None:
        """Eagerly populate ``config_manager._config`` from the DB at
        lifespan startup.

        Without this, in `db` mode a restart leaves ``_config = None``
        and the synchronous ``get_openrag_config()`` falls back to
        defaults (no yaml exists) — so ``/api/settings`` reports
        ``onboarding.current_step=0`` and the frontend flashes the
        wizard on every restart. ``load_config()`` is itself mode-aware,
        so this is safe to call unconditionally.
        """
        await self.load_config()

    async def is_onboarded(self) -> bool:
        mode = get_storage_mode()
        if mode == "files":
            return self._cm.load_config().edited

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                meta = await repo.get_section("meta") or {}
                if "edited" in meta:
                    return bool(meta["edited"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("is_onboarded DB read failed", error=str(exc))

        if mode == "db":
            return False  # no yaml fallback in pure-db mode
        return self._cm.load_config().edited

    async def get_onboarding_step(self) -> Any | None:
        """Returns the legacy step indicator — usually an int index from
        the OnboardingState dataclass, sometimes None. Treat as opaque."""
        mode = get_storage_mode()
        if mode == "files":
            return self._cm.load_config().onboarding.current_step

        try:
            async with self._session_factory() as session:
                repo = WorkspaceConfigRepo(session)
                ob = await repo.get_section("onboarding") or {}
                if "current_step" in ob:
                    return ob.get("current_step")
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_onboarding_step DB read failed", error=str(exc))

        if mode == "db":
            return None
        return self._cm.load_config().onboarding.current_step

    # ------------------------------------------------------------------
    # Write paths
    # ------------------------------------------------------------------

    async def save_config(
        self,
        config: OpenRAGConfig | None = None,
        *,
        preserve_edited: bool = False,
        actor_user_id: str | None = None,
    ) -> bool:
        mode = get_storage_mode()

        # Yaml write — only when file_writes are enabled.
        if file_writes_enabled():
            try:
                ok = self._cm.save_config_file(config, preserve_edited=preserve_edited)
                if not ok:
                    return False
            except Exception as exc:  # noqa: BLE001
                logger.error("save_config: yaml write failed", error=str(exc))
                return False
        else:
            # In `db` mode we still need to update the in-process
            # ConfigManager cache and flip `edited` so callers see the
            # new state via the legacy synchronous ``get_openrag_config()``.
            self._apply_in_memory(config, preserve_edited=preserve_edited)

        if not db_writes_enabled():
            return True

        try:
            await self._mirror_to_db(self._cm.get_config(), actor_user_id=actor_user_id)
        except Exception as exc:  # noqa: BLE001
            if mode == "db":
                logger.error("save_config: DB write failed in db mode", error=str(exc))
                return False
            logger.error("save_config: DB mirror failed (yaml ok)", error=str(exc))
        return True

    async def update_onboarding_state(
        self,
        actor_user_id: str | None = None,
        **kwargs: Any,
    ) -> bool:
        mode = get_storage_mode()

        if file_writes_enabled():
            try:
                ok = self._cm.update_onboarding_state(**kwargs)
                if not ok:
                    return False
            except Exception as exc:  # noqa: BLE001
                logger.error("update_onboarding_state: yaml failed", error=str(exc))
                return False
        else:
            # In-memory only update for db mode
            cfg = self._cm.get_config()
            for k, v in kwargs.items():
                if hasattr(cfg.onboarding, k):
                    setattr(cfg.onboarding, k, v)

        if not db_writes_enabled():
            return True

        try:
            await self._mirror_to_db(self._cm.get_config(), actor_user_id=actor_user_id)
        except Exception as exc:  # noqa: BLE001
            if mode == "db":
                logger.error("update_onboarding_state: DB write failed in db mode", error=str(exc))
                return False
            logger.error("update_onboarding_state: DB mirror failed", error=str(exc))
        return True

    # ------------------------------------------------------------------
    # Auto-mirror hook (covers legacy callers that bypass this service)
    # ------------------------------------------------------------------

    def _install_yaml_write_hooks(self) -> None:
        """Wrap ``config_manager.save_config_file`` and
        ``update_onboarding_state`` so legacy callers in
        ``src/api/settings.py`` (and elsewhere) auto-mirror to the DB
        without per-call-site changes.

        In ``db`` mode the patch SKIPS the underlying yaml write but
        still updates the in-process cache and schedules the DB mirror —
        so ``config_manager`` stays internally consistent without
        creating ``config.yaml``.
        """
        cm = self._cm
        if getattr(cm, "_db_mirror_installed", False):
            return

        # Pin the *truly original* unpatched methods on the cm BEFORE
        # any patching happens. Test cleanup may delete
        # `_db_mirror_installed` to force re-install — without this
        # capture-once attribute, the second install would close over
        # the FIRST install's patched method, building an
        # ever-deepening closure chain.
        if not hasattr(cm, "_db_mirror_original_save"):
            cm._db_mirror_original_save = cm.save_config_file  # type: ignore[attr-defined]
            cm._db_mirror_original_update_ob = cm.update_onboarding_state  # type: ignore[attr-defined]

        original_save = cm._db_mirror_original_save  # type: ignore[attr-defined]
        original_update_ob = cm._db_mirror_original_update_ob  # type: ignore[attr-defined]

        def patched_save(config=None, preserve_edited: bool = False) -> bool:
            mode = get_storage_mode()
            if mode == "db":
                # Don't write yaml; only update memory + schedule mirror.
                self._apply_in_memory(config, preserve_edited=preserve_edited)
                self._schedule_mirror()
                return True
            ok = original_save(config, preserve_edited=preserve_edited)
            if ok and db_writes_enabled():
                self._schedule_mirror()
            return ok

        def patched_update_ob(**kwargs) -> bool:
            mode = get_storage_mode()
            if mode == "db":
                cfg = cm.get_config()
                for k, v in kwargs.items():
                    if hasattr(cfg.onboarding, k):
                        setattr(cfg.onboarding, k, v)
                self._schedule_mirror()
                return True
            ok = original_update_ob(**kwargs)
            if ok and db_writes_enabled():
                self._schedule_mirror()
            return ok

        cm.save_config_file = patched_save  # type: ignore[method-assign]
        cm.update_onboarding_state = patched_update_ob  # type: ignore[method-assign]
        cm._db_mirror_installed = True  # type: ignore[attr-defined]
        logger.info(
            "WorkspaceConfigService: yaml-write hooks installed",
            mode=get_storage_mode(),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_in_memory(
        self,
        config: OpenRAGConfig | None,
        preserve_edited: bool,
    ) -> None:
        """Mirror the in-process effects of ``ConfigManager.save_config_file``
        WITHOUT touching disk — used in `db` mode so callers still see
        the cache change."""
        if config is None:
            config = self._cm.get_config()
        if not preserve_edited:
            config.edited = True
        self._cm._config = config

    def _schedule_mirror(self) -> None:
        """Fire-and-forget DB mirror of the current config_manager state.

        Runs as a tracked asyncio Task on the active loop. Three
        guarantees:
          1. The config snapshot is captured at SCHEDULE time, not at
             task-run time — so rapid `save(A)` then `save(B)` mirrors
             *both* states in order, not B twice.
          2. An asyncio.Lock serializes mirror writes, preventing two
             concurrent ``UPSERT`` against the same row.
          3. The task is tracked in ``self._pending_mirrors`` so the
             shutdown handler can await it before disposing the engine.

        If there's no running loop (sync test context) the mirror is
        skipped; the next async-aware caller catches up.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        # Snapshot NOW. Reading at task-run time would race with
        # subsequent saves to the in-memory config.
        config_snapshot = self._cm.get_config()

        async def _do_mirror():
            try:
                async with self._mirror_lock:
                    await self._mirror_to_db(config_snapshot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DB mirror after yaml save failed", error=str(exc))

        task = loop.create_task(_do_mirror())
        self._pending_mirrors.add(task)
        task.add_done_callback(self._pending_mirrors.discard)

    async def _mirror_to_db(
        self,
        config: OpenRAGConfig,
        *,
        actor_user_id: str | None = None,
    ) -> None:
        config_dict = config.to_dict()

        providers = dict(config_dict.get("providers", {}))
        for prov_name, prov_data in providers.items():
            if isinstance(prov_data, dict) and "api_key" in prov_data and prov_data["api_key"]:
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
