"""Reset workspace onboarding state so the wizard shows again.

Updates ``workspace_config`` (and config.yaml in hybrid/files mode).
Does not delete OpenSearch documents, Langflow flows, or conversations —
use the API ``rollback_onboarding`` endpoint for a full teardown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.config_manager import OnboardingState, config_manager
from config.storage_mode import db_writes_enabled, file_writes_enabled, get_storage_mode
from db.repositories.workspace_config_repo import WorkspaceConfigRepo
from utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OnboardingResetResult:
    dry_run: bool
    reset_models: bool
    storage_mode: str
    db_updated: bool = False
    yaml_updated: bool = False
    previous_edited: bool | None = None
    previous_step: Any = None

    def as_log_kwargs(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "reset_models": self.reset_models,
            "storage_mode": self.storage_mode,
            "db_updated": self.db_updated,
            "yaml_updated": self.yaml_updated,
            "previous_edited": self.previous_edited,
            "previous_step": self.previous_step,
        }


def _fresh_onboarding_dict() -> dict[str, Any]:
    return asdict(OnboardingState())


def _apply_model_reset(section: dict[str, Any], *, llm: bool) -> dict[str, Any]:
    updated = dict(section or {})
    if llm:
        updated["llm_model"] = ""
        updated["llm_provider"] = "openai"
    else:
        updated["embedding_model"] = ""
        updated["embedding_provider"] = "openai"
    return updated


async def reset_onboarding_in_db(
    session: AsyncSession,
    *,
    reset_models: bool = False,
    dry_run: bool = False,
) -> OnboardingResetResult:
    result = OnboardingResetResult(
        dry_run=dry_run,
        reset_models=reset_models,
        storage_mode=get_storage_mode(),
    )

    repo = WorkspaceConfigRepo(session)
    rows = await repo.list_all()

    meta = dict(rows.get("meta") or {})
    onboarding = dict(rows.get("onboarding") or {})
    result.previous_edited = bool(meta.get("edited", False))
    result.previous_step = onboarding.get("current_step")

    meta["edited"] = False
    fresh_onboarding = _fresh_onboarding_dict()

    if not dry_run:
        await repo.upsert("meta", meta)
        await repo.upsert("onboarding", fresh_onboarding)
        if reset_models:
            await repo.upsert(
                "agent",
                _apply_model_reset(rows.get("agent") or {}, llm=True),
            )
            await repo.upsert(
                "knowledge",
                _apply_model_reset(rows.get("knowledge") or {}, llm=False),
            )
        result.db_updated = True

    logger.info("Onboarding reset in DB", **result.as_log_kwargs())
    return result


def reset_onboarding_yaml(*, reset_models: bool = False, dry_run: bool = False) -> bool:
    """Reset onboarding flags in config.yaml (hybrid / files mode)."""
    if dry_run:
        return False

    config = config_manager.load_config()
    config.edited = False
    config.onboarding = OnboardingState()
    if reset_models:
        config.agent.llm_model = ""
        config.agent.llm_provider = "openai"
        config.knowledge.embedding_model = ""
        config.knowledge.embedding_provider = "openai"

    config_manager._config = config
    return config_manager.save_config_file(config)


async def reset_onboarding(
    session: AsyncSession | None = None,
    *,
    reset_models: bool = False,
    dry_run: bool = False,
) -> OnboardingResetResult:
    """Reset onboarding across the active storage backend(s)."""
    mode = get_storage_mode()
    result = OnboardingResetResult(
        dry_run=dry_run,
        reset_models=reset_models,
        storage_mode=mode,
    )

    if db_writes_enabled():
        if session is None:
            raise ValueError("session is required when DB writes are enabled")
        db_result = await reset_onboarding_in_db(
            session,
            reset_models=reset_models,
            dry_run=dry_run,
        )
        result.db_updated = db_result.db_updated
        result.previous_edited = db_result.previous_edited
        result.previous_step = db_result.previous_step

    if file_writes_enabled():
        result.yaml_updated = reset_onboarding_yaml(
            reset_models=reset_models,
            dry_run=dry_run,
        )

    return result
