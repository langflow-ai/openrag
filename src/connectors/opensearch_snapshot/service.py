"""Orchestration for the OpenSearch snapshot import connector.

Everything with business rules lives here so the HTTP layer (``api.py``) and
the task processor (``processor.py``) stay thin: ownership and visibility,
admission (limits, reservations), job reservation, role lifecycle, the access
probe, DTO assembly, startup reconciliation and the retrieval contract
(``DatasetRecord`` / ``list_searchable_datasets``) consumed by search and chat.

Engine modules (naming, staging, preflight, restore, roles, fields) are
referenced as modules so each call goes through one seam that tests replace.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from config import settings as cfg
from db.models import SnapshotDataset, SnapshotImport, SnapshotSource
from db.repositories.snapshot_import_repo import (
    JOB_ACTIVE_STATES,
    JOB_RECOVERY_STATE,
    SnapshotImportRepo,
)
from observability.spans import trace_span
from utils.logging_config import get_logger

from . import fields as fields_mod
from . import models as out
from . import naming, preflight, restore, roles, staging
from . import source as source_mod

logger = get_logger(__name__)

CONNECTOR_TYPE = "opensearch_snapshot"
_MAX_FIELD_CACHE = 512
_NAME_ATTEMPTS = 8
ALL_JOB_STATES = ("idle", "queued", "running", "failed", "cancelled", JOB_RECOVERY_STATE)


class SnapshotError(Exception):
    """A user-facing failure; ``api`` renders it as ``{error, code, **extra}``."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def not_found(what: str = "Not found") -> SnapshotError:
    return SnapshotError(404, "not_found", what)


# ── seams (replaced in tests) ────────────────────────────────────────────


def session_factory():
    from db import engine

    if engine.SessionLocal is None:
        engine.init_engine()
    return engine.SessionLocal


@asynccontextmanager
async def admin_os_client() -> AsyncIterator[Any]:
    """OpenSearch client with index/snapshot/security administration rights."""
    client = cfg.clients.create_index_admin_opensearch_client()
    try:
        yield client
    finally:
        await client.close()


@asynccontextmanager
async def optional_admin_os_client() -> AsyncIterator[Any]:
    """Like ``admin_os_client`` but yields None when no admin client can be built."""
    try:
        cm = admin_os_client()
        client = await cm.__aenter__()
    except Exception as exc:  # noqa: BLE001 - listing must work without OpenSearch admin access
        logger.warning("Admin OpenSearch client unavailable", error=str(exc))
        yield None
        return
    try:
        yield client
    finally:
        await cm.__aexit__(None, None, None)


def build_snapshot_source(row: SnapshotSource):
    """A ``SnapshotSource`` for a stored row; re-validates the endpoint policy."""
    location = source_mod.S3Location(
        bucket=row.bucket,
        prefix=row.prefix or "",
        region=row.region,
        endpoint_url=row.endpoint_url,
        access_key=decrypt_key(row.access_key_enc),
        secret_key=decrypt_key(row.secret_key_enc),
        path_style=row.path_style,
        verify_tls=row.verify_tls,
    )
    try:
        return source_mod.SnapshotSource(location)
    except (source_mod.SnapshotSourceError, ValueError) as exc:
        raise SnapshotError(400, "endpoint_rejected", str(exc)) from exc


def encrypt_key(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    from utils.encryption import encrypt_secret

    value = encrypt_secret(plaintext)
    return json.dumps(value) if isinstance(value, dict) else value


def decrypt_key(stored: str | None) -> str | None:
    if not stored:
        return None
    from utils.encryption import decrypt_secret

    payload: Any = stored
    if stored.lstrip().startswith("{"):
        payload = json.loads(stored)
    return decrypt_secret(payload)


# ── availability / config ────────────────────────────────────────────────


def availability() -> tuple[bool, str | None]:
    return cfg.is_snapshot_import_available()


def private_supported() -> bool:
    """Private (per-user) role mappings need OpenRAG-managed OpenSearch security."""
    return not cfg.IBM_AUTH_ENABLED and not roles.security_managed_externally()


def status_payload() -> out.StatusOut:
    enabled, reason = availability()
    return out.StatusOut(
        enabled=enabled,
        reason=reason,
        staging_type=cfg.get_snapshot_staging_type() if enabled else None,
        security_managed=not roles.security_managed_externally(),
        private_supported=private_supported(),
    )


# ── locks and admission reservations ─────────────────────────────────────

_import_locks: dict[str, asyncio.Lock] = {}
_admission_lock = asyncio.Lock()
_reserved_bytes: dict[str, int] = {}


def import_lock(import_id: str) -> asyncio.Lock:
    lock = _import_locks.get(import_id)
    if lock is None:
        lock = _import_locks[import_id] = asyncio.Lock()
    return lock


def release_reservation(import_id: str) -> None:
    _reserved_bytes.pop(import_id, None)


# ── dto helpers ──────────────────────────────────────────────────────────

_fields_cache: dict[str, list[Any]] = {}


def available_models() -> list[str]:
    """Qualified embedding models a dataset may use for hybrid retrieval."""
    try:
        knowledge = cfg.get_openrag_config().knowledge
        if knowledge.embedding_model:
            return [f"{knowledge.embedding_provider}:{knowledge.embedding_model}"]
    except Exception:  # noqa: BLE001 - config is optional metadata here
        logger.warning("Could not resolve embedding models for dataset retrieval")
    return []


async def dataset_fields(os_admin, concrete_index: str) -> list[Any]:
    """Flattened ``_source`` fields of a restored index (cached: indices are immutable)."""
    cached = _fields_cache.get(concrete_index)
    if cached is not None:
        return cached
    response = await os_admin.indices.get_mapping(index=concrete_index)
    mappings = (response.get(concrete_index) or next(iter(response.values()), {})).get(
        "mappings", {}
    )
    flattened = list(fields_mod.flatten_mapping(mappings))
    if len(_fields_cache) >= _MAX_FIELD_CACHE:
        _fields_cache.clear()
    _fields_cache[concrete_index] = flattened
    return flattened


def forget_fields(*concrete_indices: str) -> None:
    for name in concrete_indices:
        _fields_cache.pop(name, None)


def source_out(row: SnapshotSource) -> out.SourceOut:
    return out.SourceOut(
        id=row.id,
        name=row.name,
        endpoint_url=row.endpoint_url,
        region=row.region,
        bucket=row.bucket,
        prefix=row.prefix,
        path_style=row.path_style,
        verify_tls=row.verify_tls,
        has_credentials=bool(row.access_key_enc and row.secret_key_enc),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _vector_out(field) -> out.VectorFieldOut:
    return out.VectorFieldOut(
        name=field.name, type=field.type, dims=field.dims, engine=field.engine
    )


async def dataset_out(os_admin, ds: SnapshotDataset, *, ready: bool) -> out.DatasetOut:
    infos: list[Any] = []
    if ready and os_admin is not None:
        try:
            infos = await dataset_fields(os_admin, ds.concrete_index)
        except Exception as exc:  # noqa: BLE001 - listing must survive an unreachable index
            logger.warning("Could not read dataset mapping", dataset_id=ds.id, error=str(exc))
    return out.DatasetOut(
        id=ds.id,
        ordinal=ds.ordinal,
        source_index=ds.source_index,
        index_alias=ds.index_alias,
        display_name=ds.display_name,
        description=ds.description or "",
        doc_count=ds.doc_count,
        field_map=dict(ds.field_map or {}),
        retrieval=dict(ds.retrieval or {"mode": "lexical"}),
        fields=[out.FieldOut(name=f.name, type=f.type, dims=f.dims) for f in infos],
        vector_fields=[_vector_out(f) for f in fields_mod.vector_fields(infos)],
        available_models=available_models(),
    )


def role_json_for(imp: SnapshotImport) -> dict[str, Any] | None:
    """What an operator must provision when OpenRAG does not manage OpenSearch security."""
    if not roles.security_managed_externally():
        return None
    return roles.role_json(imp.slug, imp.os_principal, imp.shared)


async def import_out(
    repo: SnapshotImportRepo, imp: SnapshotImport, viewer_id: str, os_admin=None
) -> out.ImportOut:
    is_owner = imp.owner_user_id == viewer_id
    ready = imp.status in ("review", "active")
    datasets = [
        await dataset_out(os_admin, ds, ready=ready) for ds in await repo.list_datasets(imp.id)
    ]
    return out.ImportOut(
        id=imp.id,
        slug=imp.slug,
        name=imp.name,
        source_id=imp.source_id,
        snapshot_name=imp.snapshot_name,
        snapshot_uuid=imp.snapshot_uuid,
        written_by_version=imp.written_by_version,
        source_indices=list(imp.source_indices or []),
        staged_bytes=imp.staged_bytes,
        status=imp.status,
        generation=imp.generation,
        shared=imp.shared,
        is_owner=is_owner,
        job=out.JobOut(
            state=imp.job_state, kind=imp.job_kind, error=imp.job_error, task_id=imp.task_id
        ),
        role_json=role_json_for(imp) if is_owner else None,
        created_at=imp.created_at,
        updated_at=imp.updated_at,
        datasets=datasets,
    )


def preflight_out(result) -> out.PreflightOut:
    return out.PreflightOut(
        ok=result.ok,
        blockers=[
            out.IssueOut(code=i.code, message=i.message, index=i.index) for i in result.blockers
        ],
        warnings=[
            out.IssueOut(code=i.code, message=i.message, index=i.index) for i in result.warnings
        ],
        analyser_files=[
            out.AnalyserFileRefOut(
                index=r.index, setting=r.setting, path=r.path, inline_setting=r.inline_setting
            )
            for r in result.analyser_files
        ],
        staged_bytes=result.staged_bytes,
        restored_bytes=result.restored_bytes,
        indices=[
            out.PreflightIndexOut(
                name=i.name, created_version=i.created_version, doc_count=i.doc_count
            )
            for i in result.indices
        ],
    )


# ── ownership ────────────────────────────────────────────────────────────


async def owned_source(repo: SnapshotImportRepo, source_id: str, user_id: str) -> SnapshotSource:
    row = await repo.get_source(source_id)
    if row is None or row.owner_user_id != user_id:
        raise not_found("Source not found")
    return row


async def visible_import(repo: SnapshotImportRepo, import_id: str, user_id: str) -> SnapshotImport:
    imp = await repo.get_import(import_id)
    if imp is None or (imp.owner_user_id != user_id and not imp.shared):
        raise not_found("Import not found")
    return imp


async def owned_import(repo: SnapshotImportRepo, import_id: str, user_id: str) -> SnapshotImport:
    imp = await repo.get_import(import_id)
    if imp is None or imp.owner_user_id != user_id:
        raise not_found("Import not found")
    return imp


def reserved_generation(imp: SnapshotImport) -> int:
    """Generation a re-import job builds: the one reserved at admission, always above the serving one."""
    return max(imp.attempt_generation, imp.generation + 1)


def ensure_mutable(imp: SnapshotImport, *, allow_recovery: bool = False) -> None:
    if imp.status == "deleting":
        raise SnapshotError(409, "deleting", "Import is being deleted")
    if imp.job_state in JOB_ACTIVE_STATES:
        raise SnapshotError(409, "job_in_progress", "Another job is running for this import")
    if imp.job_state == JOB_RECOVERY_STATE and not allow_recovery:
        raise SnapshotError(
            409,
            "recovery_required",
            "A previous job left this import awaiting recovery; try again shortly or delete the import",
        )


# ── sources ──────────────────────────────────────────────────────────────


def _checked_keys(access_key: str | None, secret_key: str | None) -> None:
    if bool(access_key) != bool(secret_key):
        raise SnapshotError(
            400, "invalid_credentials", "Provide both access_key and secret_key, or neither"
        )


async def _connect_source(row: SnapshotSource) -> None:
    src = build_snapshot_source(row)
    try:
        await src.test_connection()
    except (source_mod.SnapshotSourceError, ValueError) as exc:
        raise SnapshotError(400, "connection_failed", str(exc)) from exc


def _validated_endpoint(url: str | None) -> str | None:
    from . import endpoint_policy

    try:
        return endpoint_policy.validate_endpoint(url or None)
    except ValueError as exc:
        raise SnapshotError(400, "endpoint_rejected", str(exc)) from exc


async def create_source(user_id: str, body) -> out.SourceOut:
    _checked_keys(body.access_key, body.secret_key)
    endpoint = _validated_endpoint(body.endpoint_url)
    row = SnapshotSource(
        id=str(uuid.uuid4()),
        owner_user_id=user_id,
        name=body.name,
        endpoint_url=endpoint,
        region=body.region,
        bucket=body.bucket,
        prefix=body.prefix.strip("/"),
        path_style=body.path_style,
        verify_tls=body.verify_tls,
        access_key_enc=encrypt_key(body.access_key),
        secret_key_enc=encrypt_key(body.secret_key),
    )
    await _connect_source(row)
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        await repo.add_source(row)
        await session.commit()
    return source_out(row)


async def list_sources(user_id: str) -> list[out.SourceOut]:
    async with session_factory()() as session:
        return [source_out(r) for r in await SnapshotImportRepo(session).list_sources(user_id)]


async def update_source(user_id: str, source_id: str, body) -> out.SourceOut:
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        row = await owned_source(repo, source_id, user_id)
        changes = body.model_dump(exclude_unset=True)
        access_key, secret_key = changes.pop("access_key", None), changes.pop("secret_key", None)
        if bool(access_key) != bool(secret_key):
            raise SnapshotError(
                400, "invalid_credentials", "Provide both access_key and secret_key, or neither"
            )
        if "endpoint_url" in changes:
            changes["endpoint_url"] = _validated_endpoint(changes["endpoint_url"])
        if "prefix" in changes and changes["prefix"] is not None:
            changes["prefix"] = changes["prefix"].strip("/")
        for key, value in changes.items():
            if value is not None or key == "endpoint_url":
                setattr(row, key, value)
        if access_key:
            row.access_key_enc, row.secret_key_enc = (
                encrypt_key(access_key),
                encrypt_key(secret_key),
            )
        await _connect_source(row)
        from datetime import UTC, datetime

        row.updated_at = datetime.now(UTC)
        session.add(row)
        await session.commit()
        return source_out(row)


async def delete_source(user_id: str, source_id: str) -> None:
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        row = await owned_source(repo, source_id, user_id)
        if await repo.count_imports_for_source(source_id):
            raise SnapshotError(
                409, "source_in_use", "Delete the imports created from this source first"
            )
        await repo.delete_source(row)
        await session.commit()


async def list_snapshots(user_id: str, source_id: str) -> out.SnapshotListOut:
    async with session_factory()() as session:
        row = await owned_source(SnapshotImportRepo(session), source_id, user_id)
    src = build_snapshot_source(row)
    try:
        generation = await src.repository_generation()
        snapshots = await src.list_snapshots()
    except (source_mod.SnapshotSourceError, ValueError) as exc:
        raise SnapshotError(400, "source_error", str(exc)) from exc
    return out.SnapshotListOut(
        repository_generation=generation,
        snapshots=[
            out.SnapshotOut(
                name=s.name,
                uuid=s.uuid,
                state=str(s.state),
                version=None if s.version is None else str(s.version),
                indices=[
                    out.SnapshotIndexOut(name=i.name, size_bytes=i.size_bytes) for i in s.indices
                ],
            )
            for s in snapshots
        ],
    )


# ── preflight ────────────────────────────────────────────────────────────


async def run_preflight(
    row: SnapshotSource,
    snapshot: str,
    indices: Sequence[str],
    *,
    existing_uuids: Sequence[str] = (),
    replaced_bytes: int = 0,
):
    src = build_snapshot_source(row)
    with trace_span("snapshot_import.preflight", source_id=row.id, indices=len(indices)) as span:
        async with admin_os_client() as os_admin:
            try:
                result = await preflight.run_preflight(
                    src,
                    snapshot,
                    list(indices),
                    os_admin=os_admin,
                    staging=staging.get_staging_store(),
                    existing_snapshot_uuids=set(existing_uuids),
                    replaced_bytes=replaced_bytes,
                    max_import_bytes=cfg.get_snapshot_max_import_bytes(),
                )
            except (source_mod.SnapshotSourceError, staging.StagingError, ValueError) as exc:
                span.fail("preflight_error")
                raise SnapshotError(400, "source_error", str(exc)) from exc
        span.set(
            ok=result.ok,
            blockers=len(result.blockers),
            staged_bytes=result.staged_bytes,
            restored_bytes=result.restored_bytes,
            error_codes=",".join(sorted({b.code for b in result.blockers})),
        )
    return result


async def preflight_for_source(user_id: str, source_id: str, snapshot: str, indices: Sequence[str]):
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        row = await owned_source(repo, source_id, user_id)
        existing = await repo.known_snapshot_uuids(user_id, source_id)
    return preflight_out(await run_preflight(row, snapshot, indices, existing_uuids=existing))


# ── imports: creation ────────────────────────────────────────────────────


def _issue_payload(result) -> list[dict[str, Any]]:
    return [{"code": i.code, "message": i.message, "index": i.index} for i in result.blockers]


def build_inlines(result, analyser_files) -> dict[str, dict[str, list[str]]]:
    try:
        return restore.build_analyser_inlines(
            result.analyser_files,
            [f.model_dump() for f in analyser_files],
            cfg.get_snapshot_max_analyser_file_bytes(),
        )
    except restore.AnalyserFileError as exc:
        raise SnapshotError(422, "analyser_mismatch", str(exc)) from exc


async def _reserve_space(import_id: str, staged_bytes: int) -> None:
    """Hold staged bytes in-process until the job ends. Caller holds the admission lock.

    Only the request that already won the DB job reservation may call this: the DB row is
    the authority on whether a job runs, so a leftover entry for this import is stale.
    """
    free = staging.get_staging_store().free_bytes()
    others = sum(size for key, size in _reserved_bytes.items() if key != import_id)
    if free is not None and others + staged_bytes > free:
        raise SnapshotError(
            409, "insufficient_disk_staging", "Not enough staging space for this import"
        )
    _reserved_bytes[import_id] = staged_bytes


def _check_privacy(shared: bool) -> None:
    if not shared and not private_supported():
        raise SnapshotError(
            409,
            "private_not_supported",
            "Private imports need OpenRAG-managed OpenSearch security; share the import instead",
        )


async def create_import(user, user_client, body, task_service) -> tuple[out.ImportOut, str]:
    """Validate, admit and enqueue a new import. Returns ``(import, task_id)``."""
    user_id = user.user_id
    _check_privacy(body.shared)
    indices = sorted(set(body.indices))
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        source_row = await owned_source(repo, body.source_id, user_id)
        existing = await repo.known_snapshot_uuids(user_id, source_row.id)

    result = await run_preflight(source_row, body.snapshot, indices, existing_uuids=existing)
    if not result.ok or result.blockers:
        raise SnapshotError(
            422,
            "preflight_failed",
            "Preflight found blocking issues",
            blockers=_issue_payload(result),
        )
    inlines = build_inlines(result, body.analyser_files)

    principal: str | None = None
    if private_supported():
        try:
            principal = await roles.lookup_principal(user_client)
        except Exception as exc:  # noqa: BLE001
            if not body.shared:
                raise SnapshotError(
                    502, "principal_lookup_failed", "Could not resolve your OpenSearch identity"
                ) from exc
            logger.warning("OpenSearch principal lookup failed for a shared import", error=str(exc))

    import_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with _admission_lock:
        async with session_factory()() as session:
            repo = SnapshotImportRepo(session)
            if await repo.count_user_imports(user_id) >= cfg.get_snapshot_max_imports_per_user():
                raise SnapshotError(
                    409, "import_limit", "Import limit reached; delete an import first"
                )
            slug = await _unique_slug(repo)
            await _reserve_space(import_id, result.staged_bytes)
            try:
                imp = SnapshotImport(
                    id=import_id,
                    slug=slug,
                    name=body.name,
                    source_id=source_row.id,
                    owner_user_id=user_id,
                    os_principal=principal,
                    shared=body.shared,
                    snapshot_name=body.snapshot,
                    snapshot_uuid=result.snapshot_uuid or "",
                    written_by_version=result.written_by_version,
                    source_indices=indices,
                    staged_bytes=result.staged_bytes,
                    status="staging",
                    generation=1,
                    job_state="queued",
                    job_kind="import",
                    task_id=task_id,
                    analyser_inlines=inlines,
                )
                datasets = _new_datasets(imp, indices)
                await repo.add_import(imp, datasets)
                await session.commit()
            except BaseException:
                release_reservation(import_id)
                raise
    await _enqueue(task_service, user, import_id, imp.name, task_id, kind="import")
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        fresh = await repo.get_import(import_id)
        return await import_out(repo, fresh, user_id), task_id


async def _unique_slug(repo: SnapshotImportRepo) -> str:
    for _ in range(_NAME_ATTEMPTS):
        slug = naming.new_slug()
        if await repo.get_import_by_slug(slug) is None:
            return slug
    raise SnapshotError(500, "slug_exhausted", "Could not allocate an import name")


def _new_datasets(imp: SnapshotImport, indices: Sequence[str]) -> list[SnapshotDataset]:
    datasets = []
    for ordinal, name in enumerate(indices):
        alias = naming.alias_name(imp.slug, ordinal)
        concrete = naming.concrete_name(imp.slug, ordinal, imp.generation)
        try:
            naming.assert_outside_user_patterns(alias)
            naming.assert_outside_user_patterns(concrete)
        except naming.NamingError as exc:
            raise SnapshotError(500, "naming_conflict", str(exc)) from exc
        datasets.append(
            SnapshotDataset(
                id=str(uuid.uuid4()),
                import_id=imp.id,
                ordinal=ordinal,
                source_index=name,
                index_alias=alias,
                concrete_index=concrete,
                display_name=name[:256],
                description="",
                field_map={},
                retrieval=fields_mod.default_retrieval(),
                doc_count=0,
            )
        )
    return datasets


async def _enqueue(
    task_service, user, import_id: str, name: str, task_id: str, *, kind: str, **processor_args
):
    """Start the job; on failure release the reservation and surface a failed job."""
    from .processor import SnapshotImportProcessor

    processor = SnapshotImportProcessor(
        import_id=import_id,
        kind=kind,
        user_id=user.user_id,
        jwt_token=getattr(user, "jwt_token", None),
        document_service=task_service.document_service,
        models_service=task_service.models_service,
        session_manager=getattr(task_service, "session_manager", None),
        ingestion_timeout=getattr(task_service, "ingestion_timeout", None),
        **processor_args,
    )
    try:
        await task_service.create_custom_task(
            user.user_id,
            [import_id],
            processor,
            original_filenames={import_id: name},
            existing_task_id=task_id,
        )
    except BaseException as exc:
        release_reservation(import_id)
        await fail_job(import_id, kind, f"Could not start job: {exc}")
        raise


async def fail_job(
    import_id: str, kind: str, error: str, *, state: str = "failed", keep_publication: bool = False
) -> None:
    """Terminal job state without touching a previously usable generation.

    ``state="recovery"`` (with ``keep_publication``) records that aliases/indices could not be
    reconciled and must be before the import accepts another job.
    """
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await repo.get_import(import_id)
        if imp is None:
            return
        values: dict[str, Any] = {"job_state": state, "job_error": error[:2000]}
        if not keep_publication:
            values["pending_publication"] = None
        if kind == "import" and imp.status != "deleting":
            values["status"] = "failed"
        if imp.status == "deleting" and kind != "delete":
            values = {}  # the delete job owns the lifecycle now
        if values:
            await repo.update_import(import_id, **values)
        await session.commit()


# ── imports: queries ─────────────────────────────────────────────────────


async def list_imports(user_id: str) -> list[out.ImportOut]:
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        rows = await repo.list_visible_imports(user_id)
        async with optional_admin_os_client() as os_admin:
            return [
                await import_out(repo, r, user_id, os_admin)
                for r in rows
                if r.status != "deleting" or r.owner_user_id == user_id
            ]


async def get_import(user_id: str, import_id: str) -> out.ImportOut:
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await visible_import(repo, import_id, user_id)
        async with optional_admin_os_client() as os_admin:
            return await import_out(repo, imp, user_id, os_admin)


# ── imports: dataset mapping, activation, sharing ────────────────────────


def _validate_dataset(field_map: dict, retrieval: dict, infos: Sequence[Any]) -> list[str]:
    messages = list(fields_mod.validate_field_map(field_map, infos))
    messages += fields_mod.validate_retrieval(retrieval, infos, set(available_models()))
    return messages


async def patch_dataset(user_id: str, import_id: str, dataset_id: str, body) -> out.DatasetOut:
    await recover_import(import_id)
    async with import_lock(import_id), session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        ensure_mutable(imp)
        ds = await repo.get_dataset(import_id, dataset_id)
        if ds is None:
            raise not_found("Dataset not found")
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        async with admin_os_client() as os_admin:
            if "field_map" in changes or "retrieval" in changes:
                if imp.status not in ("review", "active"):
                    raise SnapshotError(409, "not_ready", "The import has not finished restoring")
                infos = await dataset_fields(os_admin, ds.concrete_index)
                field_map = changes.get("field_map", ds.field_map or {})
                retrieval = changes.get("retrieval", ds.retrieval or fields_mod.default_retrieval())
                messages = _validate_dataset(field_map, retrieval, infos)
                if messages:
                    raise SnapshotError(
                        422, "invalid_dataset", "; ".join(messages), messages=messages
                    )
            await repo.update_dataset(dataset_id, **changes)
            await session.commit()
            await session.refresh(ds)
            return await dataset_out(os_admin, ds, ready=imp.status in ("review", "active"))


async def probe_aliases(user_client, aliases: Sequence[str]) -> list[str]:
    """Aliases the user's own token cannot search (``POST <alias>/_search {"size":0}``)."""
    failed = []
    for alias in aliases:
        try:
            await user_client.search(index=alias, body={"size": 0})
        except Exception as exc:  # noqa: BLE001 - any refusal means the dataset is not usable
            logger.info(
                "Dataset access probe failed", alias=alias, status=getattr(exc, "status_code", None)
            )
            failed.append(alias)
    return failed


async def _revoke_unactivated_role(os_admin, imp: SnapshotImport) -> None:
    """Undo a role a failed activation applied; an already active import keeps its role."""
    if imp.status == "active":
        return
    try:
        await roles.remove_role(os_admin, imp.slug)
    except Exception as exc:  # noqa: BLE001 - unsharing/reconcile revoke it again
        logger.warning(
            "Could not roll back dataset role after failed activation",
            slug=imp.slug,
            error=str(exc),
        )


async def activate_import(user_id: str, user_client, import_id: str) -> out.ImportOut:
    await recover_import(import_id)
    async with import_lock(import_id), session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        ensure_mutable(imp)
        if imp.status not in ("review", "active"):
            raise SnapshotError(409, "not_ready", "The import has not finished restoring")
        datasets = await repo.list_datasets(import_id)
        with trace_span(
            "snapshot_import.activate", import_id=import_id, datasets=len(datasets)
        ) as span:
            async with admin_os_client() as os_admin:
                problems = []
                for ds in datasets:
                    infos = await dataset_fields(os_admin, ds.concrete_index)
                    messages = _validate_dataset(ds.field_map or {}, ds.retrieval or {}, infos)
                    if messages:
                        problems.append({"dataset_id": ds.id, "messages": messages})
                if problems:
                    span.fail("field_map_invalid")
                    raise SnapshotError(
                        422,
                        "field_map_invalid",
                        "Dataset field mapping is invalid",
                        datasets=problems,
                    )
                try:
                    role_json = await roles.apply_role(
                        os_admin, imp.slug, principal=imp.os_principal, shared=imp.shared
                    )
                    failed = await probe_aliases(user_client, [ds.index_alias for ds in datasets])
                except BaseException:
                    await _revoke_unactivated_role(os_admin, imp)
                    raise
                if failed:
                    span.fail("role_not_provisioned")
                    await _revoke_unactivated_role(os_admin, imp)
                    raise SnapshotError(
                        409,
                        "role_not_provisioned",
                        "OpenSearch does not grant you access to the restored datasets yet",
                        role_json=role_json,
                    )
                await repo.update_import(import_id, status="active")
                await session.commit()
                await session.refresh(imp)
                return await import_out(repo, imp, user_id, os_admin)


async def set_shared(user_id: str, import_id: str, shared: bool) -> out.ImportOut:
    _check_privacy(shared)
    async with import_lock(import_id), session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        # Visibility is a revocation path: it stays available while a previous job awaits recovery.
        ensure_mutable(imp, allow_recovery=True)
        if not shared and not imp.os_principal:
            raise SnapshotError(
                409, "private_not_supported", "No OpenSearch identity is recorded for this import"
            )
        async with admin_os_client() as os_admin:
            if imp.status == "active":
                await roles.apply_role(
                    os_admin, imp.slug, principal=imp.os_principal, shared=shared
                )
            elif not shared:
                # A failed activation may have left a (shared) mapping behind: unsharing must
                # revoke it whatever the registry status says. Activation re-applies the role.
                await roles.remove_role(os_admin, imp.slug)
            await repo.update_import(import_id, shared=shared)
            await session.commit()
            await session.refresh(imp)
            return await import_out(repo, imp, user_id, os_admin)


# ── imports: re-import and delete ────────────────────────────────────────


async def reimport_preflight(user_id: str, import_id: str, snapshot: str) -> out.PreflightOut:
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        source_row = await owned_source(repo, imp.source_id, user_id)
        indices = list(imp.source_indices)
        replaced = imp.staged_bytes
        existing = await repo.known_snapshot_uuids(user_id, source_row.id) - {imp.snapshot_uuid}
    return preflight_out(
        await run_preflight(
            source_row, snapshot, indices, existing_uuids=existing, replaced_bytes=replaced
        )
    )


async def start_reimport(user, import_id: str, body, task_service) -> tuple[out.ImportOut, str]:
    user_id = user.user_id
    await recover_import(import_id)  # an interrupted attempt must finish its cleanup first
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        source_row = await owned_source(repo, imp.source_id, user_id)
        indices = list(imp.source_indices)
        replaced = imp.staged_bytes
        existing = await repo.known_snapshot_uuids(user_id, source_row.id) - {imp.snapshot_uuid}
        if imp.status not in ("review", "active"):
            raise SnapshotError(409, "not_ready", "Only a restored import can be re-imported")
        ensure_mutable(imp)

    result = await run_preflight(
        source_row, body.snapshot, indices, existing_uuids=existing, replaced_bytes=replaced
    )
    if not result.ok or result.blockers:
        raise SnapshotError(
            422,
            "preflight_failed",
            "Preflight found blocking issues",
            blockers=_issue_payload(result),
        )
    inlines = build_inlines(result, body.analyser_files)

    task_id = str(uuid.uuid4())
    async with import_lock(import_id), _admission_lock:
        async with session_factory()() as session:
            repo = SnapshotImportRepo(session)
            imp = await owned_import(repo, import_id, user_id)
            if imp.status not in ("review", "active"):
                raise SnapshotError(409, "not_ready", "Only a restored import can be re-imported")
            ensure_mutable(imp)  # a rival request may have won while this one ran its preflight
            # Win the DB job first; only the winner may touch the in-process byte reservation.
            # The attempt generation is reserved in the same UPDATE so no retry can ever reuse a
            # generation that an earlier attempt may still have to clean up.
            attempt = max(imp.generation, imp.attempt_generation) + 1
            if not await repo.reserve_job(
                import_id, "reimport", task_id=task_id, attempt_generation=attempt
            ):
                raise SnapshotError(
                    409, "job_in_progress", "Another job is running for this import"
                )
            try:
                await _reserve_space(import_id, result.staged_bytes)
            except BaseException:
                await session.rollback()  # hands the DB job back
                raise
            try:
                await session.commit()
            except BaseException:
                release_reservation(import_id)  # our own reservation, taken just above
                raise
    await _enqueue(
        task_service,
        user,
        import_id,
        imp.name,
        task_id,
        kind="reimport",
        snapshot=body.snapshot,
        snapshot_uuid=result.snapshot_uuid,
        analyser_inlines=inlines,
        written_by_version=result.written_by_version,
    )
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        return await import_out(repo, await repo.get_import(import_id), user_id), task_id


async def delete_import(user, import_id: str, task_service) -> out.ImportOut:
    """Mark deleting, stop any running job, then enqueue the cleanup job."""
    user_id = user.user_id
    async with import_lock(import_id), session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await owned_import(repo, import_id, user_id)
        running_task = imp.task_id if imp.job_state in JOB_ACTIVE_STATES else None
        await repo.update_import(import_id, status="deleting")
        await session.commit()
    if running_task:
        # Cancelled processors clean their own generation; they leave a
        # ``deleting`` import's lifecycle to the delete job below.
        await task_service.cancel_task(user_id, running_task)
    task_id = str(uuid.uuid4())
    async with import_lock(import_id), session_factory()() as session:
        repo = SnapshotImportRepo(session)
        await repo.reserve_job(
            import_id, "delete", allow_from=ALL_JOB_STATES, task_id=task_id, status="deleting"
        )
        await session.commit()
        name = imp.name
    release_reservation(import_id)
    await _enqueue(task_service, user, import_id, name, task_id, kind="delete")
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        return await import_out(repo, await repo.get_import(import_id), user_id)


# ── generation cleanup (shared by processor and reconcile) ───────────────


async def cleanup_generation(
    os_admin, slug: str, generation: int, ordinals: Sequence[int]
) -> list[str]:
    """Remove one generation's restored indices, repository and staged files.

    Every step is attempted; failures are returned (and logged), not raised, so
    a cleanup never masks the error that triggered it.
    """
    errors: list[str] = []
    names = [naming.concrete_name(slug, n, generation) for n in ordinals]
    steps = (
        ("indices", restore.delete_indices(os_admin, names)),
        ("repository", restore.delete_repository(os_admin, naming.repo_name(slug, generation))),
        ("staging", staging.get_staging_store().remove(slug, generation)),
    )
    for label, coro in steps:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Snapshot import cleanup step failed",
                step=label,
                slug=slug,
                generation=generation,
                error=str(exc),
            )
            errors.append(f"{label}: {exc}")
    forget_fields(*names)
    return errors


async def remove_everything(os_admin, imp_slug: str, max_generation: int) -> None:
    """Delete role, aliases/indices, repositories and staged files of an import."""
    await roles.remove_role(os_admin, imp_slug)
    await restore.delete_indices_for_slug(os_admin, imp_slug)
    for generation in range(1, max_generation + 1):
        await restore.delete_repository(os_admin, naming.repo_name(imp_slug, generation))
    await staging.get_staging_store().remove(imp_slug, None)


# ── retrieval contract ───────────────────────────────────────────────────


@dataclass(frozen=True)
class DatasetRecord:
    id: str
    import_id: str
    import_name: str
    slug: str
    ordinal: int
    source_index: str
    index_alias: str
    display_name: str
    description: str
    field_map: dict
    retrieval: dict
    shared: bool
    owner_user_id: str


async def list_searchable_datasets(user_id: str) -> list[DatasetRecord]:
    """Active datasets the user owns or that are shared; ``[]`` when unavailable.

    ``user_id`` must be the authenticated ``User.user_id`` (auth-context
    identity), the same value stored as ``owner_user_id``.
    """
    if not user_id or not availability()[0]:
        return []
    try:
        async with session_factory()() as session:
            pairs = await SnapshotImportRepo(session).list_active_datasets_for_user(user_id)
    except Exception as exc:  # noqa: BLE001 - dataset lookup must never break chat/search
        logger.warning("Dataset lookup failed", error=str(exc))
        return []
    return [
        DatasetRecord(
            id=ds.id,
            import_id=imp.id,
            import_name=imp.name,
            slug=imp.slug,
            ordinal=ds.ordinal,
            source_index=ds.source_index,
            index_alias=ds.index_alias,
            display_name=ds.display_name,
            description=ds.description or "",
            field_map=dict(ds.field_map or {}),
            retrieval=dict(ds.retrieval or {"mode": "lexical"}),
            shared=imp.shared,
            owner_user_id=imp.owner_user_id,
        )
        for imp, ds in pairs
    ]


async def list_datasets_out(user_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "import_id": r.import_id,
            "import_name": r.import_name,
            "display_name": r.display_name,
            "description": r.description,
            "source_index": r.source_index,
            "shared": r.shared,
            "is_owner": r.owner_user_id == user_id,
        }
        for r in await list_searchable_datasets(user_id)
    ]


# ── alias publication recovery ───────────────────────────────────────────


def publication_swaps(publication: dict[str, Any] | None) -> list[tuple[str, str, str | None]]:
    """``(alias, new_index, old_index|None)`` triples of a persisted publication intent."""
    return [(alias, new, old) for alias, new, old in (publication or {}).get("swaps", [])]


async def alias_targets(os_admin, alias: str) -> set[str]:
    """Concrete indices the alias points at right now (empty when it does not exist)."""
    try:
        response = await os_admin.indices.get_alias(name=alias)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "status_code", None) == 404:
            return set()
        raise
    return set(response) if isinstance(response, dict) else set()


async def restore_published_aliases(os_admin, swaps: Sequence[tuple[str, str, str | None]]) -> None:
    """Point every alias that had an old target back at it, judged on the aliases as they are.

    An attempted ``_aliases`` call may have been applied although no acknowledgement arrived
    (lost response, cancellation, crash), so the recorded intent is never trusted over the
    cluster. Raises when the real targets cannot be read or restored: the caller must then
    keep every possibly serving index and record that recovery is required.
    """
    reverse = []
    for alias, new_index, old_index in swaps:
        if old_index is None:
            continue  # first publication: nothing serves yet; deleting the new indices drops the alias
        if await alias_targets(os_admin, alias) != {old_index}:
            reverse.append((alias, old_index, new_index))
    if reverse:
        await restore.publish_aliases(os_admin, reverse)


async def _recover_locked(import_id: str) -> bool:
    """Finish what an interrupted/failed job could not. Caller holds the import lock."""
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        imp = await repo.get_import(import_id)
        if imp is None or imp.job_state != JOB_RECOVERY_STATE:
            return True
        slug, kind = imp.slug, imp.job_kind
        generation = reserved_generation(imp) if kind == "reimport" else imp.generation
        ordinals = tuple(d.ordinal for d in await repo.list_datasets(import_id))
        swaps = publication_swaps(imp.pending_publication)
    try:
        async with admin_os_client() as os_admin:
            await restore_published_aliases(os_admin, swaps)
            errors = await cleanup_generation(os_admin, slug, generation, ordinals)
            if errors:
                raise RuntimeError("; ".join(errors))
    except Exception as exc:  # noqa: BLE001 - stays in recovery; retried on the next attempt
        logger.warning("Snapshot import recovery incomplete", import_id=import_id, error=str(exc))
        return False
    async with session_factory()() as session:
        await SnapshotImportRepo(session).update_import(
            import_id, job_state="failed", pending_publication=None
        )
        await session.commit()
    return True


async def recover_import(import_id: str) -> bool:
    """Reconcile an import left in ``recovery``; True when it is (now) clear to accept jobs.

    Runs under the import lock, so a retry waits for a reconciliation in progress and can
    never stage into a generation that is still being cleaned up.
    """
    async with import_lock(import_id):
        return await _recover_locked(import_id)


# ── startup reconciliation ───────────────────────────────────────────────


@dataclass(frozen=True)
class InterruptedJob:
    import_id: str
    slug: str
    kind: str


async def mark_interrupted_jobs() -> list[InterruptedJob]:
    """Park jobs left queued/running by a previous process (task state is process-local).

    DB only and fast: it runs before the API serves requests so it cannot race with a job
    started afterwards. Imports whose job built a generation are put in ``recovery`` (not
    startable) until ``reconcile_roles``/``recover_import`` has restored aliases and removed
    that generation; an interrupted delete is simply restartable.
    """
    interrupted: list[InterruptedJob] = []
    async with session_factory()() as session:
        repo = SnapshotImportRepo(session)
        for imp in await repo.list_imports_in_job_states(JOB_ACTIVE_STATES):
            values: dict[str, Any] = {"job_error": "interrupted by restart"}
            if imp.job_kind == "delete":
                values["job_state"] = "failed"
            else:
                values["job_state"] = JOB_RECOVERY_STATE
                if imp.job_kind == "import":
                    values["status"] = "failed"
            await repo.update_import(imp.id, **values)
            interrupted.append(InterruptedJob(import_id=imp.id, slug=imp.slug, kind=imp.job_kind))
        await session.commit()
    return interrupted


async def _reconcile_role(os_admin, import_id: str) -> None:
    """Align one import's role with its status; under the import lock so it cannot undo a
    concurrent activation or visibility change with a stale status."""
    async with import_lock(import_id):
        async with session_factory()() as session:
            imp = await SnapshotImportRepo(session).get_import(import_id)
        if imp is None:
            return
        try:
            if imp.status == "active":
                await roles.apply_role(
                    os_admin, imp.slug, principal=imp.os_principal, shared=imp.shared
                )
            elif imp.status in ("review", "failed"):
                await roles.remove_role(os_admin, imp.slug)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dataset role reconcile failed", slug=imp.slug, error=str(exc))


async def reconcile_roles() -> None:
    """Finish interrupted jobs' cleanup and re-apply dataset roles after a restart.

    Skipped entirely when the feature is off. Role writes honour
    ``OPENRAG_SKIP_OS_SECURITY_SETUP`` (``roles`` makes no call then). Role invariant:
    active imports have their role, imports that never became active have none.
    """
    if not availability()[0]:
        return
    try:
        async with admin_os_client() as os_admin:
            from utils.opensearch_init import wait_for_opensearch

            await wait_for_opensearch(os_admin)
            async with session_factory()() as session:
                repo = SnapshotImportRepo(session)
                recovering = [
                    i.id for i in await repo.list_imports_in_job_states((JOB_RECOVERY_STATE,))
                ]
            for import_id in recovering:
                await recover_import(import_id)
            if roles.security_managed_externally():
                return
            async with session_factory()() as session:
                import_ids = [i.id for i in await SnapshotImportRepo(session).list_all_imports()]
            for import_id in import_ids:
                await _reconcile_role(os_admin, import_id)
    except Exception as exc:  # noqa: BLE001 - startup must not fail on reconciliation
        logger.warning("Snapshot import reconcile failed", error=str(exc))
