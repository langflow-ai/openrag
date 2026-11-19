"""Shared fakes for the snapshot-import service, processor and API tests.

Everything below the orchestration layer is replaced at the engine-module seam
(``service.restore``/``staging``/``preflight``/``roles``), so no test touches
S3, OpenSearch or the filesystem. The fake OpenSearch client is *strict*: any
call that a test did not expect fails loudly, which is how the "no security
calls under OPENRAG_SKIP_OS_SECURITY_SETUP" guarantee is proven.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

import db.models  # noqa: F401
from connectors.opensearch_snapshot import preflight, restore
from connectors.opensearch_snapshot import service as svc
from connectors.opensearch_snapshot import source as source_mod
from db.models import SnapshotDataset, SnapshotImport, SnapshotSource
from session_manager import User

SLUG = "abcdefghij"
MAPPING = {
    "properties": {
        "title": {"type": "text"},
        "body": {"type": "text"},
        "url": {"type": "keyword"},
    }
}
SAMPLES = [{"title": "Photo 51", "body": "deoxyribonucleic acid", "url": "https://example.test/1"}]


def make_user(user_id: str = "alice", jwt: str | None = "jwt-alice") -> User:
    return User(
        user_id=user_id, email=f"{user_id}@example.test", name=user_id.title(), jwt_token=jwt
    )


async def make_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ── fake OpenSearch ──────────────────────────────────────────────────────


class FakeIndices:
    def __init__(self, os_client: FakeOS):
        self._os = os_client

    async def get_mapping(self, index: str):
        self._os.calls.append(("get_mapping", index))
        return {index: {"mappings": self._os.mappings}}

    async def get_alias(self, name: str):
        self._os.calls.append(("get_alias", name))
        return dict(self._os.aliases.get(name, {}))


class FakeOS:
    """Records known calls; any other attribute access fails the test."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.mappings = MAPPING
        self.aliases: dict[str, dict] = {}
        self.indices = FakeIndices(self)

    async def close(self) -> None:
        pass

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected OpenSearch call: {name}")


class FakeUserClient:
    """The caller's own OpenSearch client; ``deny`` makes probes return 403."""

    def __init__(self, deny: bool = False):
        self.deny = deny
        self.searches: list[tuple[str, dict]] = []

    async def search(self, index: str, body: dict):
        self.searches.append((index, body))
        if self.deny:
            raise ForbiddenError()
        return {"hits": {"hits": []}}


class ForbiddenError(Exception):
    status_code = 403


# ── fake engine pieces ───────────────────────────────────────────────────


class FakeStore:
    kind = "fs"

    def __init__(self, free: int | None = None, stage_bytes: int = 1000):
        self.free = free
        self.stage_bytes = stage_bytes
        self.staged: list[tuple] = []
        self.removed: list[tuple] = []
        self.hold: asyncio.Event | None = None

    def repository_name(self, slug, generation):
        return f"openrag_stage_{slug}_g{generation}"

    def repository_body(self, slug, generation):
        return {
            "type": "fs",
            "settings": {"location": f"/staging/{slug}/g{generation}", "readonly": True},
        }

    async def stage(self, slug, generation, src, manifest, on_progress=None):
        self.staged.append((slug, generation, manifest))
        if self.hold is not None:
            await self.hold.wait()
        return self.stage_bytes

    async def remove(self, slug, generation=None):
        self.removed.append((slug, generation))

    def free_bytes(self):
        return self.free


def make_manifest(
    indices: Sequence[str] = ("idx_a", "idx_b"), total: int = 1000, snapshot: str = "snap-1"
):
    return source_mod.StagingManifest(
        snapshot_name=snapshot,
        snapshot_uuid="uuid-" + snapshot,
        repository_generation=7,
        indices=tuple(indices),
        files=(source_mod.ManifestFile(key="index.latest", size=total),),
    )


class FakeSnapshotSource:
    def __init__(self, indices: Sequence[str] = ("idx_a", "idx_b")):
        self.indices = indices
        self.manifest_calls: list[tuple] = []

    async def test_connection(self) -> None:
        return None

    async def repository_generation(self) -> int:
        return 7

    async def list_snapshots(self):
        return [
            source_mod.SnapshotInfo(
                name="snap-1",
                uuid="uuid-snap-1",
                state="SUCCESS",
                version="3.8.0",
                repository_generation=7,
                indices=tuple(
                    source_mod.IndexInfo(n, f"id-{n}", f"m-{n}", 10) for n in self.indices
                ),
            )
        ]

    async def build_manifest(self, snapshot_name, indices):
        self.manifest_calls.append((snapshot_name, tuple(indices)))
        return make_manifest(indices, snapshot=snapshot_name)


def make_preflight(
    *,
    blockers: Sequence[tuple[str, str]] = (),
    analyser: Sequence[tuple[str, str, str, str]] = (),
    indices: Sequence[str] = ("idx_a", "idx_b"),
    staged: int = 1000,
):
    return preflight.PreflightResult(
        ok=not blockers,
        blockers=tuple(preflight.Issue(code, msg) for code, msg in blockers),
        warnings=(),
        analyser_files=tuple(preflight.AnalyserFileRef(*a) for a in analyser),
        staged_bytes=staged,
        restored_bytes=staged * 2,
        indices=tuple(preflight.IndexPreflight(n, "3.8.0", 10, 5) for n in indices),
        manifest=make_manifest(indices, staged),
        written_by_version="3.8.0",
        snapshot_uuid="uuid-snap-1",
    )


class FakeTaskService:
    def __init__(self):
        self.created: list[dict] = []
        self.cancelled: list[tuple[str, str]] = []
        self.document_service = None
        self.models_service = None
        self.session_manager = None
        self.ingestion_timeout = 3600

    async def create_custom_task(
        self, user_id, items, processor, original_filenames=None, existing_task_id=None, **_
    ):
        self.created.append(
            {
                "user_id": user_id,
                "items": items,
                "processor": processor,
                "task_id": existing_task_id,
            }
        )
        return existing_task_id

    async def cancel_task(self, user_id, task_id):
        self.cancelled.append((user_id, task_id))
        return True


@dataclass
class Recorder:
    """Records engine calls and lets tests script failures."""

    calls: list[tuple] = field(default_factory=list)
    restore_failures: dict[str, Exception] = field(default_factory=dict)
    restore_gate: asyncio.Event | None = None
    mappings: dict = field(default_factory=lambda: MAPPING)

    def names(self, kind: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == kind]


def install_engine(
    monkeypatch, store: FakeStore | None = None, rec: Recorder | None = None
) -> Recorder:
    """Replace restore/staging IO with recorders; returns the recorder."""
    rec = rec or Recorder()
    store = store or FakeStore()

    async def restore_index(
        os_admin,
        *,
        repository,
        snapshot,
        source_index,
        concrete_index,
        analyser_inlines=None,
        timeout_s=0,
        poll_s=1.0,
        partial=False,
    ):
        rec.calls.append(
            (
                "restore_index",
                concrete_index,
                source_index,
                repository,
                snapshot,
                analyser_inlines,
                partial,
            )
        )
        if rec.restore_gate is not None:
            await rec.restore_gate.wait()
        if source_index in rec.restore_failures:
            raise rec.restore_failures[source_index]
        return restore.RestoreResult(concrete_index=concrete_index, doc_count=42, health="green")

    async def mapping_and_samples(os_admin, index, n=50):
        rec.calls.append(("samples", index))
        return rec.mappings, SAMPLES

    async def publish_aliases(os_admin, swaps):
        rec.calls.append(("publish_aliases", [tuple(s) for s in swaps]))

    async def delete_indices(os_admin, names):
        rec.calls.append(("delete_indices", list(names)))

    async def delete_indices_for_slug(os_admin, slug, *, keep=()):
        rec.calls.append(("delete_indices_for_slug", slug))
        return []

    async def register_repository(os_admin, name, body):
        rec.calls.append(("register_repository", name, body))

    async def delete_repository(os_admin, name):
        rec.calls.append(("delete_repository", name))

    for fn in (
        restore_index,
        publish_aliases,
        delete_indices,
        delete_indices_for_slug,
        register_repository,
        delete_repository,
    ):
        monkeypatch.setattr(restore, fn.__name__, fn)
    monkeypatch.setattr(restore, "index_mapping_and_samples", mapping_and_samples)
    monkeypatch.setattr(svc.staging, "get_staging_store", lambda: store)
    rec.store = store  # type: ignore[attr-defined]
    return rec


def install_services(
    monkeypatch, factory, os_client: FakeOS | None = None, src: FakeSnapshotSource | None = None
):
    """Point the service layer at an in-memory DB, a fake admin client and a fake source."""
    os_client = os_client or FakeOS()
    src = src or FakeSnapshotSource()
    monkeypatch.setattr(svc, "session_factory", lambda: factory)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def admin_client():
        yield os_client

    monkeypatch.setattr(svc, "admin_os_client", admin_client)
    monkeypatch.setattr(svc, "build_snapshot_source", lambda row: src)
    svc._fields_cache.clear()
    svc._reserved_bytes.clear()
    return os_client, src


def enable_feature(
    monkeypatch,
    enabled: bool = True,
    reason: str | None = None,
    *,
    skip_security: bool = False,
    ibm: bool = False,
):
    monkeypatch.setattr(
        svc.cfg,
        "is_snapshot_import_available",
        lambda: (enabled, None if enabled else (reason or "disabled")),
    )
    monkeypatch.setattr(svc.cfg, "IBM_AUTH_ENABLED", ibm)
    if skip_security:
        monkeypatch.setenv("OPENRAG_SKIP_OS_SECURITY_SETUP", "true")
    else:
        monkeypatch.delenv("OPENRAG_SKIP_OS_SECURITY_SETUP", raising=False)


# ── seeding ──────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


async def seed_source(
    factory, *, id="src-1", owner="alice", name="Fixture bucket"
) -> SnapshotSource:
    row = SnapshotSource(
        id=id,
        owner_user_id=owner,
        name=name,
        endpoint_url=None,
        region="us-east-1",
        bucket="b",
        prefix="p",
        access_key_enc=None,
        secret_key_enc=None,
    )
    async with factory() as session:
        session.add(row)
        await session.commit()
    return row


async def seed_import(
    factory,
    *,
    id="imp-1",
    slug=SLUG,
    owner="alice",
    source_id="src-1",
    status="review",
    shared=False,
    job_state="idle",
    job_kind="import",
    generation=1,
    task_id=None,
    indices=("idx_a", "idx_b"),
    field_map: dict | None = None,
    principal: str | None = "alice",
    created_offset: int = 0,
) -> SnapshotImport:
    imp = SnapshotImport(
        id=id,
        slug=slug,
        name=f"Import {id}",
        source_id=source_id,
        owner_user_id=owner,
        os_principal=principal,
        shared=shared,
        snapshot_name="snap-1",
        snapshot_uuid="uuid-snap-1",
        written_by_version="3.8.0",
        source_indices=list(indices),
        staged_bytes=1000,
        status=status,
        generation=generation,
        job_state=job_state,
        job_kind=job_kind,
        task_id=task_id,
        analyser_inlines={},
    )
    datasets = [
        SnapshotDataset(
            id=f"{id}-ds{n}",
            import_id=id,
            ordinal=n,
            source_index=name,
            index_alias=f"ds_{slug}_{n}",
            concrete_index=f"ds_{slug}_{n}_g{generation}",
            display_name=name,
            description="",
            field_map=field_map
            if field_map is not None
            else {"text_fields": ["title", "body"], "title_field": "title", "url_field": "url"},
            retrieval={"mode": "lexical"},
            doc_count=5,
        )
        for n, name in enumerate(indices)
    ]
    async with factory() as session:
        session.add(imp)
        await session.flush()
        for ds in datasets:
            session.add(ds)
        await session.commit()
    return imp


async def load_import(factory, import_id: str = "imp-1"):
    from db.repositories import SnapshotImportRepo

    async with factory() as session:
        repo = SnapshotImportRepo(session)
        imp = await repo.get_import(import_id)
        datasets = await repo.list_datasets(import_id) if imp else []
    return imp, datasets
