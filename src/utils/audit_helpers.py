"""Best-effort audit log writes usable from anywhere in the backend.

An audit write must never break the calling operation (VULN-13906 and the
existing convention in rbac_service.py::audit_denied) — failures are logged
and swallowed, not raised.
"""

from __future__ import annotations

from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)


async def write_audit_event_best_effort(
    *,
    event: str,
    actor_user_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    audit_metadata: dict[str, Any] | None = None,
) -> None:
    try:
        from db.engine import SessionLocal
        from db.repositories import AuditRepo

        async with SessionLocal() as session:
            audit = AuditRepo(session)
            await audit.write(
                event=event,
                actor_user_id=actor_user_id,
                target_type=target_type,
                target_id=target_id,
                audit_metadata=audit_metadata,
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"audit write failed for event={event}", error=str(exc))
