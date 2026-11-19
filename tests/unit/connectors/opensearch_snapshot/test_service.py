"""Snapshot import service: retrieval contract, reconciliation, status and admission."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from connectors.opensearch_snapshot import restore, roles
from connectors.opensearch_snapshot import service as svc
from connectors.opensearch_snapshot.models import ImportCreateBody, ReimportBody

from ._support import (
    SLUG,
    FakeStore,
    FakeTaskService,
    FakeUserClient,
    enable_feature,
    install_engine,
    install_services,
    load_import,
    make_preflight,
    make_session_factory,
    make_user,
    seed_import,
    seed_source,
)


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine, factory = await make_session_factory()
    enable_feature(monkeypatch)
    # asyncio locks bind to the first event loop that contends them; every test has its own loop
    monkeypatch.setattr(svc, "_import_locks", {})
    monkeypatch.setattr(svc, "_admission_lock", asyncio.Lock())
    os_client, src = install_services(monkeypatch, factory)
    rec = install_engine(monkeypatch, FakeStore())
    monkeypatch.setattr("utils.opensearch_init.wait_for_opensearch", AsyncMock())
    await seed_source(factory, id="src-1", owner="alice")
    await seed_source(factory, id="src-2", owner="bob", name="Bob bucket")
    yield type(
        "Env", (), {"factory": factory, "os": os_client, "rec": rec, "monkeypatch": monkeypatch}
    )
    await engine.dispose()


# ── list_searchable_datasets ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_searchable_datasets_are_own_and_shared_active_only(env):
    await seed_import(
        env.factory, id="a-private", slug="aaaaaaaaaa", owner="alice", status="active"
    )
    await seed_import(
        env.factory, id="a-shared", slug="bbbbbbbbbb", owner="alice", status="active", shared=True
    )
    await seed_import(env.factory, id="a-review", slug="cccccccccc", owner="alice", status="review")
    await seed_import(
        env.factory,
        id="b-private",
        slug="dddddddddd",
        source_id="src-2",
        owner="bob",
        status="active",
        principal="bob",
    )
    await seed_import(
        env.factory,
        id="b-shared",
        slug="eeeeeeeeee",
        source_id="src-2",
        owner="bob",
        status="active",
        shared=True,
        principal="bob",
    )
    await seed_import(
        env.factory,
        id="b-shared-failed",
        slug="ffffffffff",
        source_id="src-2",
        owner="bob",
        status="failed",
        shared=True,
    )
    await seed_import(
        env.factory,
        id="b-deleting",
        slug="gggggggggg",
        source_id="src-2",
        owner="bob",
        status="deleting",
        shared=True,
    )

    alice = {r.import_id for r in await svc.list_searchable_datasets("alice")}
    bob = {r.import_id for r in await svc.list_searchable_datasets("bob")}
    carol = {r.import_id for r in await svc.list_searchable_datasets("carol")}

    assert alice == {
        "a-private",
        "a-shared",
        "b-shared",
    }  # own + shared; bob's private and non-active hidden
    assert bob == {"b-private", "b-shared", "a-shared"}
    assert carol == {"a-shared", "b-shared"}


@pytest.mark.asyncio
async def test_dataset_record_carries_the_retrieval_contract(env):
    await seed_import(env.factory, id="a1", slug=SLUG, status="active", shared=True)

    records = await svc.list_searchable_datasets("alice")

    assert [(r.ordinal, r.source_index) for r in records] == [(0, "idx_a"), (1, "idx_b")]
    first = records[0]
    assert isinstance(first, svc.DatasetRecord)
    assert (first.id, first.import_id, first.import_name, first.slug) == (
        "a1-ds0",
        "a1",
        "Import a1",
        SLUG,
    )
    assert first.index_alias == f"ds_{SLUG}_0"  # the alias, never the concrete generation
    assert first.display_name == "idx_a" and first.description == ""
    assert first.field_map["title_field"] == "title" and first.retrieval == {"mode": "lexical"}
    assert (first.shared, first.owner_user_id) == (True, "alice")


@pytest.mark.asyncio
async def test_searchable_datasets_are_empty_when_unavailable_or_anonymous(env):
    await seed_import(env.factory, id="a1", status="active", shared=True)

    assert await svc.list_searchable_datasets("") == []
    enable_feature(env.monkeypatch, enabled=False, reason="disabled")
    assert await svc.list_searchable_datasets("alice") == []


@pytest.mark.asyncio
async def test_dataset_lookup_failure_never_breaks_callers(env):
    def broken():
        raise RuntimeError("db down")

    env.monkeypatch.setattr(svc, "session_factory", broken)
    assert await svc.list_searchable_datasets("alice") == []


# ── reconciliation ───────────────────────────────────────────────────────


async def _set(factory, import_id: str = "imp-1", **values):
    from db.repositories import SnapshotImportRepo

    async with factory() as session:
        await SnapshotImportRepo(session).update_import(import_id, **values)
        await session.commit()


def _publication(generation: int, *pairs: tuple[int, int | None], slug: str = SLUG) -> dict:
    """Persisted publication intent: dataset n moves from generation ``old`` to ``generation``."""
    return {
        "generation": generation,
        "swaps": [
            [
                f"ds_{slug}_{n}",
                f"ds_{slug}_{n}_g{generation}",
                None if old is None else f"ds_{slug}_{n}_g{old}",
            ]
            for n, old in pairs
        ],
    }


@pytest.mark.asyncio
async def test_interrupted_jobs_are_parked_in_recovery_until_their_cleanup_finishes(env):
    await seed_import(
        env.factory,
        id="init",
        slug="aaaaaaaaaa",
        status="restoring",
        job_state="running",
        job_kind="import",
    )
    await seed_import(
        env.factory,
        id="re",
        slug="bbbbbbbbbb",
        status="active",
        job_state="queued",
        job_kind="reimport",
        generation=3,
    )
    await seed_import(
        env.factory,
        id="del",
        slug="cccccccccc",
        status="deleting",
        job_state="running",
        job_kind="delete",
    )
    await seed_import(env.factory, id="idle", slug="dddddddddd", status="active")

    interrupted = {job.import_id: job for job in await svc.mark_interrupted_jobs()}

    assert {i: (j.slug, j.kind) for i, j in interrupted.items()} == {
        "init": ("aaaaaaaaaa", "import"),
        "re": ("bbbbbbbbbb", "reimport"),
        "del": ("cccccccccc", "delete"),
    }
    init, _ = await load_import(env.factory, "init")
    assert (init.status, init.job_state, init.job_error) == (
        "failed",
        "recovery",
        "interrupted by restart",
    )
    reimport, _ = await load_import(env.factory, "re")
    assert (reimport.status, reimport.job_state, reimport.generation) == (
        "active",
        "recovery",
        3,
    )  # keeps serving
    deleting, _ = await load_import(env.factory, "del")
    assert (deleting.status, deleting.job_state) == (
        "deleting",
        "failed",
    )  # a delete is simply restartable
    idle, _ = await load_import(env.factory, "idle")
    assert (idle.status, idle.job_state) == ("active", "idle")
    # B5: nothing may start (or reuse the generation) until recovery completes
    with pytest.raises(svc.SnapshotError) as exc:
        svc.ensure_mutable(reimport)
    assert exc.value.code == "recovery_required"
    svc.ensure_mutable(
        reimport, allow_recovery=True
    )  # visibility changes (revocation) stay possible


@pytest.fixture
def role_calls(env):
    applied, removed = [], []

    async def apply_role(os_admin, slug, *, principal, shared):
        applied.append((slug, principal, shared))
        return {}

    async def remove_role(os_admin, slug):
        removed.append(slug)

    env.monkeypatch.setattr(roles, "apply_role", apply_role)
    env.monkeypatch.setattr(roles, "remove_role", remove_role)
    return SimpleNamespace(applied=applied, removed=removed)


@pytest.mark.asyncio
async def test_reconcile_cleans_interrupted_generations_and_aligns_roles_with_status(
    env, role_calls
):
    await seed_import(
        env.factory, id="init", slug="aaaaaaaaaa", status="restoring", job_state="running"
    )
    await seed_import(env.factory, id="live", slug="bbbbbbbbbb", status="active", shared=True)
    await seed_import(env.factory, id="rev", slug="cccccccccc", status="review")
    await svc.mark_interrupted_jobs()

    await svc.reconcile_roles()

    assert ("delete_indices", ["ds_aaaaaaaaaa_0_g1", "ds_aaaaaaaaaa_1_g1"]) in env.rec.calls
    assert ("delete_repository", "openrag_stage_aaaaaaaaaa_g1") in env.rec.calls
    assert ("aaaaaaaaaa", 1) in env.rec.store.removed
    init, _ = await load_import(env.factory, "init")
    assert (init.status, init.job_state) == ("failed", "failed")  # recovered: now only deletable
    assert role_calls.applied == [("bbbbbbbbbb", "alice", True)]  # only active imports hold a role
    # imports that never became active hold none (a failed activation may have left one behind)
    assert sorted(role_calls.removed) == ["aaaaaaaaaa", "cccccccccc"]


@pytest.mark.asyncio
async def test_reconcile_restores_aliases_from_the_persisted_publication_after_a_crash(env):
    """B3: killed between the ``_aliases`` call and the DB commit; only the cluster knows what applied."""
    await seed_import(
        env.factory, id="re", slug=SLUG, status="active", job_state="running", job_kind="reimport"
    )
    await _set(
        env.factory, "re", attempt_generation=2, pending_publication=_publication(2, (0, 1), (1, 1))
    )
    env.os.aliases[f"ds_{SLUG}_0"] = {f"ds_{SLUG}_0_g2": {"aliases": {}}}  # dataset 0 already moved
    env.os.aliases[f"ds_{SLUG}_1"] = {f"ds_{SLUG}_1_g1": {"aliases": {}}}  # dataset 1 never did
    await svc.mark_interrupted_jobs()

    await svc.reconcile_roles()

    # only the alias that really moved is pointed back, then the unused generation is removed
    assert env.rec.names("publish_aliases") == [
        ("publish_aliases", [(f"ds_{SLUG}_0", f"ds_{SLUG}_0_g1", f"ds_{SLUG}_0_g2")])
    ]
    order = [c[0] for c in env.rec.calls]
    assert order.index("publish_aliases") < order.index("delete_indices")
    assert ("delete_indices", [f"ds_{SLUG}_0_g2", f"ds_{SLUG}_1_g2"]) in env.rec.calls
    imp, _ = await load_import(env.factory, "re")
    assert (imp.job_state, imp.pending_publication, imp.generation) == ("failed", None, 1)


@pytest.mark.asyncio
async def test_reconcile_never_deletes_a_generation_whose_alias_rollback_fails(env):
    """B4 across restarts: the import stays in recovery with its publication intent until it works."""
    await seed_import(
        env.factory, id="re", slug=SLUG, status="active", job_state="running", job_kind="reimport"
    )
    await _set(
        env.factory, "re", attempt_generation=2, pending_publication=_publication(2, (0, 1), (1, 1))
    )
    env.os.aliases[f"ds_{SLUG}_0"] = {f"ds_{SLUG}_0_g2": {"aliases": {}}}
    env.os.aliases[f"ds_{SLUG}_1"] = {f"ds_{SLUG}_1_g2": {"aliases": {}}}
    await svc.mark_interrupted_jobs()
    healthy = {"on": False}
    real_publish = restore.publish_aliases

    async def publish_aliases(os_admin, swaps):
        if not healthy["on"]:
            raise restore.RestoreError("opensearch unavailable")
        return await real_publish(os_admin, swaps)

    env.monkeypatch.setattr(restore, "publish_aliases", publish_aliases)

    await svc.reconcile_roles()

    assert env.rec.names("delete_indices") == []
    imp, _ = await load_import(env.factory, "re")
    assert (imp.job_state, imp.pending_publication) == ("recovery", _publication(2, (0, 1), (1, 1)))

    healthy["on"] = True
    assert await svc.recover_import("re") is True
    assert len(env.rec.names("publish_aliases")) == 1
    assert ("delete_indices", [f"ds_{SLUG}_0_g2", f"ds_{SLUG}_1_g2"]) in env.rec.calls
    imp, _ = await load_import(env.factory, "re")
    assert (imp.job_state, imp.pending_publication) == ("failed", None)


@pytest.mark.asyncio
async def test_reconcile_under_skip_cleans_up_but_makes_no_security_calls(env):
    enable_feature(env.monkeypatch, skip_security=True)
    env.monkeypatch.setattr(
        roles, "apply_role", AsyncMock(side_effect=AssertionError("security write under SKIP"))
    )
    await seed_import(
        env.factory, id="init", slug="aaaaaaaaaa", status="restoring", job_state="running"
    )
    await seed_import(env.factory, id="live", slug="bbbbbbbbbb", status="active", shared=True)
    await seed_import(env.factory, id="rev", slug="cccccccccc", status="review")
    await svc.mark_interrupted_jobs()

    await (
        svc.reconcile_roles()
    )  # the real remove_role is a no-op under SKIP; FakeOS would fail any call

    assert ("delete_indices", ["ds_aaaaaaaaaa_0_g1", "ds_aaaaaaaaaa_1_g1"]) in env.rec.calls


@pytest.mark.asyncio
async def test_reconcile_does_nothing_when_the_feature_is_off(env):
    enable_feature(env.monkeypatch, enabled=False)
    await seed_import(env.factory, id="init", status="restoring", job_state="recovery")

    await svc.reconcile_roles()

    assert env.rec.calls == [] and env.os.calls == []


@pytest.mark.asyncio
async def test_reconcile_never_raises_when_opensearch_is_unreachable(env):
    env.monkeypatch.setattr(
        "utils.opensearch_init.wait_for_opensearch", AsyncMock(side_effect=RuntimeError("down"))
    )
    await svc.reconcile_roles()  # logged, not raised: startup must not fail


# ── admission ────────────────────────────────────────────────────────────


def _create_body(**overrides) -> ImportCreateBody:
    return ImportCreateBody(
        source_id="src-1",
        snapshot="snap-1",
        indices=["idx_a", "idx_b"],
        name="Scientists",
        **overrides,
    )


@pytest.fixture
def admit(env):
    async def run_preflight(src, snapshot, indices, **kwargs):
        return make_preflight(staged=600)

    async def lookup(client):
        return "alice"

    env.monkeypatch.setattr(svc.preflight, "run_preflight", run_preflight)
    env.monkeypatch.setattr(roles, "lookup_principal", lookup)
    return env


@pytest.mark.asyncio
async def test_staging_space_is_reserved_in_process_across_admissions(admit):
    admit.monkeypatch.setattr(svc.staging, "get_staging_store", lambda: FakeStore(free=1000))
    tasks = FakeTaskService()

    first, _ = await svc.create_import(make_user("alice"), object(), _create_body(), tasks)
    assert svc._reserved_bytes == {first.id: 600}

    with pytest.raises(svc.SnapshotError) as exc:
        await svc.create_import(make_user("alice"), object(), _create_body(), tasks)
    assert exc.value.code == "insufficient_disk_staging"

    svc.release_reservation(first.id)  # the first job finished
    second, _ = await svc.create_import(make_user("alice"), object(), _create_body(), tasks)
    assert second.id != first.id


@pytest.mark.asyncio
async def test_failed_enqueue_releases_the_reservation_and_marks_the_import_failed(admit):
    class BrokenTasks(FakeTaskService):
        async def create_custom_task(self, *args, **kwargs):
            raise RuntimeError("queue unavailable")

    with pytest.raises(RuntimeError):
        await svc.create_import(make_user("alice"), object(), _create_body(), BrokenTasks())

    assert svc._reserved_bytes == {}
    (imp,) = await _all_imports(admit.factory)
    assert (imp.status, imp.job_state) == (
        "failed",
        "failed",
    ) and "queue unavailable" in imp.job_error


async def _all_imports(factory):
    from db.repositories import SnapshotImportRepo

    async with factory() as session:
        return await SnapshotImportRepo(session).list_all_imports()


@pytest.mark.asyncio
async def test_job_reservation_is_atomic_in_the_database(env):
    from db.repositories import SnapshotImportRepo

    await seed_import(env.factory, id="imp-1", status="active")
    async with env.factory() as session:
        repo = SnapshotImportRepo(session)
        assert await repo.reserve_job("imp-1", "reimport", task_id="t1") is True
        assert await repo.reserve_job("imp-1", "reimport", task_id="t2") is False  # already queued
        await session.commit()
        await repo.update_import("imp-1", job_state="failed")
        assert (
            await repo.reserve_job("imp-1", "reimport", task_id="t3") is True
        )  # failed jobs may be retried
        await session.commit()
    imp, _ = await load_import(env.factory, "imp-1")
    assert (imp.job_state, imp.task_id) == ("queued", "t3")


# ── naming and identity ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_physical_names_never_contain_source_index_names(admit):
    from connectors.opensearch_snapshot import naming

    imported, _ = await svc.create_import(
        make_user("alice"), object(), _create_body(), FakeTaskService()
    )

    assert naming.is_valid_slug(imported.slug)
    for ds in imported.datasets:
        assert ds.source_index not in ds.index_alias
    imp, datasets = await load_import(admit.factory, imported.id)
    assert all(ds.source_index not in ds.concrete_index for ds in datasets)
    assert imp.owner_user_id == "alice"  # User.user_id, the same value retrieval uses


def test_status_payload_reflects_gate_and_security_mode(monkeypatch):
    enable_feature(monkeypatch, enabled=False, reason="storage_mode")
    payload = svc.status_payload()
    assert (payload.enabled, payload.reason, payload.staging_type) == (False, "storage_mode", None)

    enable_feature(monkeypatch, skip_security=True)
    monkeypatch.setattr(svc.cfg, "get_snapshot_staging_type", lambda: "fs")
    payload = svc.status_payload()
    assert (
        payload.enabled,
        payload.security_managed,
        payload.private_supported,
        payload.staging_type,
    ) == (True, False, False, "fs")


# ── re-import admission and recovery gating (B5, B8) ─────────────────────


@pytest.mark.asyncio
async def test_retry_waits_for_the_interrupted_attempts_cleanup_and_never_reuses_its_generation(
    admit,
):
    """B5: reconciliation of generation 2 is in flight when the user retries the re-import."""
    await seed_import(
        admit.factory, id="imp-1", status="active", job_state="running", job_kind="reimport"
    )
    await _set(admit.factory, attempt_generation=2)
    await svc.mark_interrupted_jobs()
    admit.monkeypatch.setattr(roles, "apply_role", AsyncMock(return_value={}))
    cleaning, release = asyncio.Event(), asyncio.Event()
    cleaned: list[str] = []
    real_delete = restore.delete_indices

    async def gated_delete(os_admin, names):
        cleaning.set()
        await release.wait()
        cleaned.extend(names)
        await real_delete(os_admin, names)

    admit.monkeypatch.setattr(restore, "delete_indices", gated_delete)
    tasks = FakeTaskService()

    reconcile = asyncio.create_task(svc.reconcile_roles())
    await asyncio.wait_for(cleaning.wait(), 5)  # reconciliation is deleting generation 2
    retry = asyncio.create_task(
        svc.start_reimport(make_user("alice"), "imp-1", ReimportBody(snapshot="snap-2"), tasks)
    )
    await asyncio.sleep(0.05)
    assert (
        not retry.done() and tasks.created == []
    )  # the retry cannot stage into generation 2 meanwhile

    release.set()
    await reconcile
    await asyncio.wait_for(retry, 5)

    assert cleaned == [f"ds_{SLUG}_0_g2", f"ds_{SLUG}_1_g2"]
    imp, _ = await load_import(admit.factory)
    assert (imp.job_state, imp.job_kind, imp.generation) == ("queued", "reimport", 1)
    assert imp.attempt_generation == 3  # reserved strictly above the generation that was cleaned
    assert tasks.created[0]["processor"].kind == "reimport"


@pytest.mark.asyncio
async def test_mutations_are_refused_while_recovery_cannot_complete(admit):
    await seed_import(
        admit.factory, id="imp-1", status="active", job_state="recovery", job_kind="reimport"
    )
    await _set(admit.factory, attempt_generation=2)

    async def failing_delete(os_admin, names):
        raise restore.RestoreError("opensearch unavailable")

    admit.monkeypatch.setattr(restore, "delete_indices", failing_delete)
    tasks = FakeTaskService()

    with pytest.raises(svc.SnapshotError) as retry:
        await svc.start_reimport(
            make_user("alice"), "imp-1", ReimportBody(snapshot="snap-2"), tasks
        )
    with pytest.raises(svc.SnapshotError) as activate:
        await svc.activate_import("alice", object(), "imp-1")

    assert (retry.value.code, activate.value.code) == ("recovery_required", "recovery_required")
    assert tasks.created == [] and svc._reserved_bytes == {}
    assert (await load_import(admit.factory))[0].job_state == "recovery"


@pytest.mark.asyncio
async def test_retry_recovers_inline_when_the_startup_reconciliation_could_not(admit):
    await seed_import(
        admit.factory, id="imp-1", status="active", job_state="recovery", job_kind="reimport"
    )
    await _set(admit.factory, attempt_generation=2)
    tasks = FakeTaskService()

    await svc.start_reimport(make_user("alice"), "imp-1", ReimportBody(snapshot="snap-2"), tasks)

    assert ("delete_indices", [f"ds_{SLUG}_0_g2", f"ds_{SLUG}_1_g2"]) in admit.rec.calls
    assert (await load_import(admit.factory))[0].attempt_generation == 3


@pytest.mark.asyncio
async def test_simultaneous_reimports_leave_the_winners_reservation_intact(admit):
    """B8: both requests pass the early checks and wait in preflight, then race for the job."""
    await seed_import(admit.factory, id="imp-1", status="active")
    admit.monkeypatch.setattr(svc.staging, "get_staging_store", lambda: FakeStore(free=1000))
    arrived: list[str] = []
    both = asyncio.Event()

    async def run_preflight(src, snapshot, indices, **kwargs):
        arrived.append(snapshot)
        if len(arrived) == 2:
            both.set()
        await both.wait()
        return make_preflight(staged=600)

    admit.monkeypatch.setattr(svc.preflight, "run_preflight", run_preflight)
    tasks = FakeTaskService()

    results = await asyncio.gather(
        svc.start_reimport(make_user("alice"), "imp-1", ReimportBody(snapshot="snap-2"), tasks),
        svc.start_reimport(make_user("alice"), "imp-1", ReimportBody(snapshot="snap-3"), tasks),
        return_exceptions=True,
    )

    (loser,) = [r for r in results if isinstance(r, Exception)]
    assert isinstance(loser, svc.SnapshotError) and loser.code == "job_in_progress"
    assert svc._reserved_bytes == {"imp-1": 600}  # the winner's reservation survived the loser
    assert len(tasks.created) == 1
    imp, _ = await load_import(admit.factory)
    assert (imp.job_state, imp.attempt_generation) == ("queued", 2)


@pytest.mark.asyncio
async def test_failed_space_reservation_hands_the_db_job_back(admit):
    await seed_import(admit.factory, id="imp-1", status="active")
    admit.monkeypatch.setattr(svc.staging, "get_staging_store", lambda: FakeStore(free=100))

    with pytest.raises(svc.SnapshotError) as exc:
        await svc.start_reimport(
            make_user("alice"), "imp-1", ReimportBody(snapshot="snap-2"), FakeTaskService()
        )

    assert exc.value.code == "insufficient_disk_staging" and svc._reserved_bytes == {}
    imp, _ = await load_import(admit.factory)
    assert (imp.job_state, imp.attempt_generation) == (
        "idle",
        0,
    )  # still startable, nothing reserved


# ── role lifecycle on visibility changes (B2) ────────────────────────────


@pytest.fixture
def security(env):
    """Role mappings of a security-enabled cluster: who can read ``ds_<slug>_*`` directly."""
    mappings: dict[str, dict] = {}
    behaviour = SimpleNamespace(remove_fails=False)

    async def apply_role(os_admin, slug, *, principal, shared):
        mappings[slug] = {"backend_roles": ["openrag_user"]} if shared else {"users": [principal]}
        return {"role_name": f"openrag_ds_{slug}"}

    async def remove_role(os_admin, slug):
        if behaviour.remove_fails:
            raise roles.RoleError("the OpenSearch security API is unavailable")
        mappings.pop(slug, None)

    def can_read(slug: str, *, user: str, backend_roles: tuple[str, ...] = ()) -> bool:
        mapping = mappings.get(slug) or {}
        return user in mapping.get("users", []) or bool(
            set(backend_roles) & set(mapping.get("backend_roles", []))
        )

    env.monkeypatch.setattr(roles, "apply_role", apply_role)
    env.monkeypatch.setattr(roles, "remove_role", remove_role)
    return SimpleNamespace(mappings=mappings, behaviour=behaviour, can_read=can_read)


@pytest.mark.asyncio
async def test_failed_activation_rolls_back_the_shared_mapping_it_applied(env, security):
    await seed_import(env.factory, status="review", shared=True)

    with pytest.raises(svc.SnapshotError) as exc:
        await svc.activate_import(
            "alice", FakeUserClient(deny=True), "imp-1"
        )  # alice is outside the shared role

    assert exc.value.code == "role_not_provisioned"
    assert SLUG not in security.mappings
    assert not security.can_read(SLUG, user="bob", backend_roles=("openrag_user",))
    assert (await load_import(env.factory))[0].status == "review"


@pytest.mark.asyncio
async def test_unsharing_after_a_failed_activation_revokes_a_mapping_the_rollback_missed(
    env, security
):
    await seed_import(env.factory, status="review", shared=True)
    security.behaviour.remove_fails = True  # the rollback itself cannot reach the security API

    with pytest.raises(svc.SnapshotError):
        await svc.activate_import("alice", FakeUserClient(deny=True), "imp-1")
    assert security.can_read(
        SLUG, user="bob", backend_roles=("openrag_user",)
    )  # the window B2 describes

    security.behaviour.remove_fails = False
    result = await svc.set_shared("alice", "imp-1", False)

    assert result.shared is False and (await load_import(env.factory))[0].shared is False
    assert not security.can_read(
        SLUG, user="bob", backend_roles=("openrag_user",)
    )  # revoked, not just relabelled
    # activating again gives the owner (and only the owner) direct access
    await svc.activate_import("alice", FakeUserClient(), "imp-1")
    assert security.can_read(SLUG, user="alice")
    assert not security.can_read(SLUG, user="bob", backend_roles=("openrag_user",))


@pytest.mark.asyncio
async def test_unsharing_an_import_in_recovery_still_revokes(env, security):
    await seed_import(
        env.factory, status="active", job_state="recovery", job_kind="reimport", shared=True
    )
    security.mappings[SLUG] = {"backend_roles": ["openrag_user"]}

    await svc.set_shared("alice", "imp-1", False)

    assert security.mappings[SLUG] == {"users": ["alice"]}
