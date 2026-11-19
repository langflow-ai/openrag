"""HTTP routes for the OpenSearch snapshot import connector.

Internal API (``tags=["internal"]``): the browser reaches it as
``/api/connectors/opensearch_snapshot/...``. Every route except ``/status`` is
gated on the feature (404 when unavailable); ownership violations are 404.
Errors render as ``{"error": message, "code": code, **extra}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse

from dependencies import get_current_user, get_session_manager, get_task_service, require_permission
from session_manager import User

from . import models as out
from . import service as svc
from .models import (
    DatasetPatchBody,
    ImportCreateBody,
    PreflightBody,
    ReimportBody,
    ReimportPreflightBody,
    ShareBody,
    SourceCreateBody,
    SourcePatchBody,
)


def require_snapshot_import_enabled() -> None:
    enabled, _reason = svc.availability()
    if not enabled:
        raise HTTPException(status_code=404, detail="OpenSearch snapshot import is not enabled")


async def snapshot_error_handler(_request, exc: svc.SnapshotError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": exc.message, "code": exc.code, **exc.extra},
    )


def _user_client(session_manager, user: User):
    return session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)


# ── status ───────────────────────────────────────────────────────────────


async def get_status(user: User = Depends(get_current_user)) -> out.StatusOut:
    return svc.status_payload()


# ── sources ──────────────────────────────────────────────────────────────


async def create_source(
    body: SourceCreateBody,
    user: User = Depends(require_permission("connectors:create")),
):
    result = await svc.create_source(user.user_id, body)
    return JSONResponse(status_code=201, content=result.model_dump(mode="json"))


async def list_sources(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"sources": await svc.list_sources(user.user_id)}


async def patch_source(
    source_id: str,
    body: SourcePatchBody,
    user: User = Depends(get_current_user),
) -> out.SourceOut:
    return await svc.update_source(user.user_id, source_id, body)


async def delete_source(
    source_id: str,
    user: User = Depends(require_permission("connectors:delete:own")),
) -> dict[str, bool]:
    await svc.delete_source(user.user_id, source_id)
    return {"deleted": True}


async def list_snapshots(
    source_id: str, user: User = Depends(get_current_user)
) -> out.SnapshotListOut:
    return await svc.list_snapshots(user.user_id, source_id)


async def source_preflight(
    source_id: str,
    body: PreflightBody,
    user: User = Depends(get_current_user),
) -> out.PreflightOut:
    return await svc.preflight_for_source(user.user_id, source_id, body.snapshot, body.indices)


# ── imports ──────────────────────────────────────────────────────────────


async def create_import(
    body: ImportCreateBody,
    task_service=Depends(get_task_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:create")),
):
    imported, task_id = await svc.create_import(
        user, _user_client(session_manager, user), body, task_service
    )
    return JSONResponse(
        status_code=202,
        content={"import": imported.model_dump(mode="json"), "task_id": task_id},
    )


async def list_imports(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"imports": await svc.list_imports(user.user_id)}


async def get_import(import_id: str, user: User = Depends(get_current_user)) -> out.ImportOut:
    return await svc.get_import(user.user_id, import_id)


async def patch_dataset(
    import_id: str,
    dataset_id: str,
    body: DatasetPatchBody,
    user: User = Depends(get_current_user),
) -> out.DatasetOut:
    return await svc.patch_dataset(user.user_id, import_id, dataset_id, body)


async def activate_import(
    import_id: str,
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
) -> out.ImportOut:
    return await svc.activate_import(user.user_id, _user_client(session_manager, user), import_id)


async def share_import(
    import_id: str,
    body: ShareBody,
    user: User = Depends(get_current_user),
) -> out.ImportOut:
    return await svc.set_shared(user.user_id, import_id, body.shared)


async def reimport_preflight(
    import_id: str,
    body: ReimportPreflightBody,
    user: User = Depends(get_current_user),
) -> out.PreflightOut:
    return await svc.reimport_preflight(user.user_id, import_id, body.snapshot)


async def reimport(
    import_id: str,
    body: ReimportBody,
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    imported, task_id = await svc.start_reimport(user, import_id, body, task_service)
    return JSONResponse(
        status_code=202,
        content={"import": imported.model_dump(mode="json"), "task_id": task_id},
    )


async def delete_import(
    import_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(require_permission("connectors:delete:own")),
):
    imported = await svc.delete_import(user, import_id, task_service)
    return JSONResponse(status_code=202, content={"import": imported.model_dump(mode="json")})


# ── datasets ─────────────────────────────────────────────────────────────


async def list_datasets(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"datasets": await svc.list_datasets_out(user.user_id)}
