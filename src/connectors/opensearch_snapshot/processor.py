"""Task processor for snapshot import jobs: import, re-import and delete.

One ``process_item`` call runs one whole job under the task's
``ingestion_timeout``. Staging, restores and publication share that budget; the
processor keeps its own slightly shorter deadline so a timeout is told apart
from a user cancellation and cleanup still has time to run.

Failure contract (R12, R14, R15):
* cleanup of the generation being built always runs shielded from cancellation;
* an initial import ends ``failed``; a re-import keeps the previous generation
  ``active`` and only records ``job_state``/``job_error``;
* aliases move in one ``_aliases`` call and are moved back if the DB commit (or
  the post-publish access probe) fails;
* staged files and the staging repository are removed after a successful restore.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any

from config import settings as cfg
from db.repositories.snapshot_import_repo import JOB_RECOVERY_STATE, SnapshotImportRepo
from models.processors import TaskProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from observability.spans import trace_span
from utils.logging_config import get_logger

from . import fields as fields_mod
from . import naming, restore, staging
from . import service as svc
from . import source as source_mod

logger = get_logger(__name__)

DEADLINE_HEADROOM_MAX_SECONDS = 120
MIN_RESTORE_TIMEOUT_SECONDS = 60.0
_USER_SAFE_ERRORS = (
    restore.RestoreError,
    restore.AnalyserFileError,
    staging.StagingError,
    source_mod.SnapshotSourceError,
    svc.SnapshotError,
)


class _Superseded(Exception):
    """The import is being deleted; the delete job owns what happens next."""


class _FieldMapIncompatible(Exception):
    pass


@dataclass
class _Run:
    """Mutable bookkeeping for one job, consulted by the failure path."""

    slug: str = ""
    generation: int = 0
    ordinals: tuple[int, ...] = ()
    swaps: list[tuple[str, str, str | None]] = field(default_factory=list)
    publication_attempted: bool = False
    committed: bool = False
    staged: bool = False


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


class SnapshotImportProcessor(TaskProcessor):
    def __init__(
        self,
        *,
        import_id: str,
        kind: str,
        user_id: str,
        jwt_token: str | None = None,
        document_service=None,
        models_service=None,
        session_manager=None,
        ingestion_timeout: int | None = None,
        snapshot: str | None = None,
        analyser_inlines: dict[str, dict[str, list[str]]] | None = None,
        written_by_version: str | None = None,
        snapshot_uuid: str | None = None,
    ):
        super().__init__(document_service=document_service, models_service=models_service)
        self.import_id = import_id
        self.kind = kind
        self.user_id = user_id
        self.jwt_token = jwt_token
        self.session_manager = session_manager
        self.ingestion_timeout = ingestion_timeout
        self.snapshot = snapshot
        self.analyser_inlines = analyser_inlines
        self.written_by_version = written_by_version
        self.snapshot_uuid = snapshot_uuid
        self._deadline: float | None = None
        self._run_state = _Run()

    # ── task contract ────────────────────────────────────────────────────

    async def process_item(self, upload_task: UploadTask, item: str, file_task: FileTask) -> None:
        self._run_state = _Run()
        self._deadline = self._compute_deadline()
        started = time.monotonic()
        try:
            summary = await self._guarded()
        except asyncio.CancelledError:
            await asyncio.shield(self._fail("Import was cancelled.", state="cancelled"))
            self._finish_failed(upload_task, file_task, "Import was cancelled.")
            raise
        except _Superseded:
            await asyncio.shield(self._cleanup_generation())
            self._finish_failed(upload_task, file_task, "Import was deleted.")
        except TimeoutError:
            message = f"Import timed out after {self.ingestion_timeout} seconds."
            await asyncio.shield(self._fail(message))
            self._finish_failed(upload_task, file_task, message)
        except Exception as exc:  # noqa: BLE001
            message = self._safe_message(exc)
            logger.error(
                "Snapshot import job failed",
                import_id=self.import_id,
                kind=self.kind,
                error=str(exc),
                exc_info=True,
            )
            await asyncio.shield(self._fail(message))
            self._finish_failed(upload_task, file_task, message)
        else:
            summary["seconds"] = round(time.monotonic() - started, 1)
            file_task.status, file_task.error, file_task.result, file_task.updated_at = (
                TaskStatus.COMPLETED,
                None,
                summary,
                time.time(),
            )
            upload_task.successful_files += 1
        finally:
            svc.release_reservation(self.import_id)

    @staticmethod
    def _finish_failed(upload_task: UploadTask, file_task: FileTask, message: str) -> None:
        file_task.status, file_task.error, file_task.updated_at = (
            TaskStatus.FAILED,
            message,
            time.time(),
        )
        upload_task.failed_files += 1

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        """Engine errors are user-safe by contract; anything else stays in the log."""
        if isinstance(exc, _FieldMapIncompatible):
            return str(exc)
        if isinstance(exc, _USER_SAFE_ERRORS):
            return str(exc) or exc.__class__.__name__
        return "Import failed unexpectedly; see the server log."

    def _compute_deadline(self) -> float | None:
        if not self.ingestion_timeout:
            return None
        headroom = min(DEADLINE_HEADROOM_MAX_SECONDS, self.ingestion_timeout // 10)
        return asyncio.get_running_loop().time() + max(1, self.ingestion_timeout - headroom)

    def _remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return self._deadline - asyncio.get_running_loop().time()

    async def _guarded(self) -> dict[str, Any]:
        remaining = self._remaining()
        async with asyncio.timeout(remaining):
            if self.kind == "delete":
                return await self._run_delete()
            return await self._run_import()

    # ── delete ───────────────────────────────────────────────────────────

    async def _run_delete(self) -> dict[str, Any]:
        async with svc.session_factory()() as session:
            repo = SnapshotImportRepo(session)
            imp = await repo.get_import(self.import_id)
            if imp is None:
                return {"deleted": False, "reason": "already deleted"}
            slug, generation = imp.slug, max(imp.generation, imp.attempt_generation)
            await repo.update_import(self.import_id, job_state="running")
            await session.commit()
        with trace_span("snapshot_import.delete", import_id=self.import_id, slug=slug) as span:
            try:
                async with svc.admin_os_client() as os_admin:
                    await svc.remove_everything(os_admin, slug, generation + 1)
            except Exception:
                span.fail("delete_failed")
                raise
        async with svc.session_factory()() as session:
            await SnapshotImportRepo(session).delete_import(self.import_id)
            await session.commit()
        return {"deleted": True}

    # ── import / re-import ───────────────────────────────────────────────

    async def _run_import(self) -> dict[str, Any]:
        reimport = self.kind == "reimport"
        async with svc.session_factory()() as session:
            repo = SnapshotImportRepo(session)
            imp = await repo.get_import(self.import_id)
            if imp is None or imp.status == "deleting":
                raise _Superseded()
            source_row = await repo.get_source(imp.source_id)
            datasets = await repo.list_datasets(self.import_id)
            if source_row is None:
                raise svc.SnapshotError(400, "source_missing", "The import source no longer exists")
            values: dict[str, Any] = {"job_state": "running", "job_error": None}
            if not reimport:
                values["status"] = "staging"
            await repo.update_import(self.import_id, **values)
            await session.commit()

        slug = imp.slug
        # A re-import builds the generation reserved for it at admission (strictly above every
        # generation an earlier attempt may still have to clean up).
        generation = svc.reserved_generation(imp) if reimport else imp.generation
        snapshot = (self.snapshot if reimport else imp.snapshot_name) or imp.snapshot_name
        expected_uuid = self.snapshot_uuid if reimport else imp.snapshot_uuid
        inlines = (
            self.analyser_inlines
            if self.analyser_inlines is not None
            else (imp.analyser_inlines or {})
        )
        indices = list(imp.source_indices)
        state = self._run_state
        state.slug, state.generation = slug, generation
        state.ordinals = tuple(d.ordinal for d in datasets)

        src = svc.build_snapshot_source(source_row)
        store = staging.get_staging_store()
        repo_name = naming.repo_name(slug, generation)

        with trace_span(
            "snapshot_import.stage", import_id=imp.id, generation=generation, kind=self.kind
        ) as span:
            try:
                manifest = await _maybe_await(src.build_manifest(snapshot, indices))
                self._check_identity(manifest, expected_uuid, snapshot)
                if manifest.total_bytes > cfg.get_snapshot_max_import_bytes():
                    raise svc.SnapshotError(
                        422, "too_large", "Import exceeds the configured size limit"
                    )
                state.staged = True
                staged_bytes = await store.stage(slug, generation, src, manifest)
            except Exception:
                span.fail("stage_failed")
                raise
            span.set(bytes=staged_bytes, files=len(manifest.files), manifest=manifest.kind)

        partial = await self._is_partial(src, snapshot)
        if not reimport:
            await self._set_import(status="restoring")
        async with svc.admin_os_client() as os_admin:
            await restore.register_repository(
                os_admin, repo_name, store.repository_body(slug, generation)
            )

            restored: dict[int, tuple[str, int, list[Any], dict[str, Any]]] = {}
            for ds in datasets:
                concrete = naming.concrete_name(slug, ds.ordinal, generation)
                with trace_span(
                    "snapshot_import.restore",
                    import_id=imp.id,
                    ordinal=ds.ordinal,
                    generation=generation,
                ) as span:
                    try:
                        result = await restore.restore_index(
                            os_admin,
                            repository=repo_name,
                            snapshot=snapshot,
                            source_index=ds.source_index,
                            concrete_index=concrete,
                            analyser_inlines=inlines.get(ds.source_index) or None,
                            timeout_s=self._restore_timeout(),
                            partial=partial,
                        )
                        mappings, samples = await restore.index_mapping_and_samples(
                            os_admin, concrete
                        )
                    except Exception:
                        span.fail("restore_failed")
                        raise
                    infos = list(fields_mod.flatten_mapping(mappings))
                    restored[ds.ordinal] = (
                        concrete,
                        result.doc_count,
                        infos,
                        fields_mod.suggest_field_map(infos, samples),
                    )
                    span.set(doc_count=result.doc_count, health=result.health)

            if reimport:
                self._check_field_maps(datasets, restored)

            await self._publish(os_admin, datasets, restored, generation, reimport)
            await self._commit(
                datasets,
                restored,
                generation=generation,
                reimport=reimport,
                staged_bytes=staged_bytes,
                snapshot=snapshot,
                snapshot_uuid=manifest.snapshot_uuid,
                inlines=inlines,
            )
            state.committed = True

            if reimport:
                old = [d.concrete_index for d in datasets]
                try:
                    await restore.delete_indices(os_admin, old)
                except Exception as exc:  # noqa: BLE001 - the new generation already serves
                    logger.warning(
                        "Old generation cleanup failed", import_id=imp.id, error=str(exc)
                    )
                svc.forget_fields(*old)

        # Data now lives in the indices; staged files and the staging repo are dead weight.
        async with svc.admin_os_client() as os_admin:
            await svc.cleanup_generation(os_admin, slug, generation, ())
        return {
            "import_id": imp.id,
            "generation": generation,
            "datasets": len(datasets),
            "staged_bytes": staged_bytes,
        }

    @staticmethod
    def _check_identity(manifest, expected_uuid: str | None, snapshot: str) -> None:
        """The job restores exactly the snapshot preflight admitted, or nothing.

        Snapshot contents are immutable, so the UUID pins the admitted metadata, analyser
        refs and sizes; a snapshot deleted and recreated under the same name has a new UUID.
        """
        if not expected_uuid or manifest.snapshot_uuid != expected_uuid:
            raise svc.SnapshotError(
                409,
                "snapshot_changed",
                f"Snapshot {snapshot!r} is not the snapshot that was admitted (it was replaced or its identity "
                "was not recorded); run preflight again",
            )

    @staticmethod
    async def _is_partial(src, snapshot: str) -> bool:
        """PARTIAL snapshots need ``partial: true`` on restore."""
        try:
            infos = await src.list_snapshots()
        except Exception as exc:  # noqa: BLE001 - the restore itself reports real problems
            logger.warning("Could not determine snapshot state", error=str(exc))
            return False
        return any(info.name == snapshot and info.state == "PARTIAL" for info in infos)

    def _restore_timeout(self) -> float:
        remaining = self._remaining()
        return 3600.0 if remaining is None else max(MIN_RESTORE_TIMEOUT_SECONDS, remaining)

    async def _set_import(self, **values: Any) -> None:
        async with svc.session_factory()() as session:
            await SnapshotImportRepo(session).update_import(self.import_id, **values)
            await session.commit()

    @staticmethod
    def _check_field_maps(datasets, restored) -> None:
        """A re-import must not silently invalidate confirmed field maps."""
        for ds in datasets:
            if not ds.field_map:
                continue
            _, _, infos, _ = restored[ds.ordinal]
            messages = list(fields_mod.validate_field_map(ds.field_map, infos))
            messages += fields_mod.validate_retrieval(
                ds.retrieval or fields_mod.default_retrieval(), infos, set(svc.available_models())
            )
            if messages:
                raise _FieldMapIncompatible(
                    f"field_map_incompatible: dataset {ds.source_index!r}: "
                    + "; ".join(messages)
                    + " (the previous generation keeps serving)"
                )

    async def _publish(self, os_admin, datasets, restored, generation: int, reimport: bool) -> None:
        swaps = [
            (ds.index_alias, restored[ds.ordinal][0], ds.concrete_index if reimport else None)
            for ds in datasets
        ]
        state = self._run_state
        state.swaps = swaps
        with trace_span(
            "snapshot_import.publish", import_id=self.import_id, generation=generation
        ) as span:
            try:
                if reimport:
                    # Intent first: whatever happens to this process or request after the
                    # ``_aliases`` call, recovery can inspect the real alias targets.
                    await self._set_import(
                        pending_publication={
                            "generation": generation,
                            "swaps": [list(s) for s in swaps],
                        }
                    )
                state.publication_attempted = (
                    True  # possibly applied from here on, acknowledged or not
                )
                await restore.publish_aliases(os_admin, swaps)
            except Exception:
                span.fail("publish_failed")
                raise
            if reimport:
                await self._probe(datasets)

    async def _probe(self, datasets) -> None:
        """After publishing, the owner's effective token must search every new alias (HTTP 200).

        Anything else (403, 401, 5xx, timeout, no way to build the client) is a failed
        publication: the failure path restores the old aliases and keeps the old generation.
        """
        if self.session_manager is None:
            raise svc.SnapshotError(
                502, "probe_unavailable", "Could not verify access to the new generation"
            )
        try:
            # ``jwt_token`` may be absent (no-auth mode): the session manager mints the effective token.
            client = self.session_manager.get_user_opensearch_client(self.user_id, self.jwt_token)
        except Exception as exc:  # noqa: BLE001
            raise svc.SnapshotError(
                502, "probe_unavailable", "Could not verify access to the new generation"
            ) from exc
        for ds in datasets:
            try:
                await client.search(index=ds.index_alias, body={"size": 0})
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "status_code", None) == 403:
                    raise svc.SnapshotError(
                        409,
                        "role_not_provisioned",
                        "The new generation is not readable with your access",
                    ) from exc
                logger.warning(
                    "Re-import access probe failed", alias=ds.index_alias, error=str(exc)
                )
                raise svc.SnapshotError(
                    502, "probe_failed", "Could not verify access to the new generation"
                ) from exc

    async def _commit(
        self,
        datasets,
        restored,
        *,
        generation,
        reimport,
        staged_bytes,
        snapshot,
        snapshot_uuid,
        inlines,
    ):
        async with svc.session_factory()() as session:
            repo = SnapshotImportRepo(session)
            for ds in datasets:
                concrete, doc_count, _infos, suggested = restored[ds.ordinal]
                values: dict[str, Any] = {"concrete_index": concrete, "doc_count": doc_count}
                if not (reimport and ds.field_map):
                    values["field_map"] = suggested
                await repo.update_dataset(ds.id, **values)
            import_values: dict[str, Any] = {
                "generation": generation,
                "staged_bytes": staged_bytes,
                "job_state": "idle",
                "job_error": None,
                "analyser_inlines": inlines,
                "snapshot_uuid": snapshot_uuid,  # the identity admitted by preflight and verified before staging
                "pending_publication": None,  # the DB now references the published generation
            }
            if reimport:
                import_values["snapshot_name"] = snapshot
                if self.written_by_version:
                    import_values["written_by_version"] = self.written_by_version
            else:
                import_values["status"] = "review"
            await repo.update_import(self.import_id, **import_values)
            await session.commit()

    # ── failure paths (always run shielded) ──────────────────────────────

    async def _cleanup_generation(self) -> bool:
        """Undo this attempt. True when it could not be fully reconciled (recovery required).

        An attempted alias publication may have been applied whether or not an acknowledgement
        arrived, so the real alias targets are inspected and the old ones restored *before*
        anything is deleted. If that fails the new indices may still be serving: they are kept.
        """
        state = self._run_state
        if not state.slug or state.committed:
            return False
        try:
            async with svc.admin_os_client() as os_admin:
                if state.publication_attempted:
                    try:
                        await svc.restore_published_aliases(os_admin, state.swaps)
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Alias rollback failed; keeping the new generation",
                            import_id=self.import_id,
                            error=str(exc),
                        )
                        return True
                errors = await svc.cleanup_generation(
                    os_admin, state.slug, state.generation, state.ordinals
                )
                return bool(errors)
        except Exception as exc:  # noqa: BLE001
            logger.error("Snapshot import cleanup failed", import_id=self.import_id, error=str(exc))
            return True

    async def _fail(self, message: str, *, state: str = "failed") -> None:
        recovery = self.kind != "delete" and await self._cleanup_generation()
        try:
            if recovery:
                await svc.fail_job(
                    self.import_id,
                    self.kind,
                    message,
                    state=JOB_RECOVERY_STATE,
                    keep_publication=True,
                )
            else:
                await svc.fail_job(self.import_id, self.kind, message, state=state)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Could not record snapshot import failure", import_id=self.import_id, error=str(exc)
            )
