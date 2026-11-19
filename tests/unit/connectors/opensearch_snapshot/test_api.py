"""HTTP contract of the snapshot import connector (FastAPI app, sqlite, fakes)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request

from connectors.opensearch_snapshot import endpoint_policy, restore, roles
from connectors.opensearch_snapshot import service as svc
from connectors.opensearch_snapshot.connector import OpenSearchSnapshotConnector
from dependencies import get_session_manager, get_task_service

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

PREFIX = "/connectors/opensearch_snapshot"


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine, factory = await make_session_factory()
    enable_feature(monkeypatch)
    os_client, src = install_services(monkeypatch, factory)
    store = FakeStore()
    rec = install_engine(monkeypatch, store)
    tasks = FakeTaskService()
    user_client = FakeUserClient()
    role_calls: list[dict] = []

    async def apply_role(os_admin, slug, *, principal, shared):
        role_calls.append({"slug": slug, "principal": principal, "shared": shared})
        return {"role_name": f"openrag_ds_{slug}"}

    async def lookup_principal(client):
        return "alice-principal"

    real_apply_role = roles.apply_role
    real_remove_role = roles.remove_role
    removed_roles: list[str] = []

    async def remove_role(os_admin, slug):
        removed_roles.append(slug)

    monkeypatch.setattr(roles, "apply_role", apply_role)
    monkeypatch.setattr(roles, "remove_role", remove_role)
    monkeypatch.setattr(roles, "lookup_principal", lookup_principal)
    # asyncio locks bind to the first event loop that contends them; every test has its own loop
    monkeypatch.setattr(svc, "_import_locks", {})
    monkeypatch.setattr(svc, "_admission_lock", asyncio.Lock())

    preflights: list[dict] = []
    result_box = {"result": make_preflight()}

    async def run_preflight(src_, snapshot, indices, **kwargs):
        preflights.append({"snapshot": snapshot, "indices": list(indices), **kwargs})
        return result_box["result"]

    monkeypatch.setattr(svc.preflight, "run_preflight", run_preflight)

    app = FastAPI()
    OpenSearchSnapshotConnector.register_routes(app)
    users = {name: make_user(name, f"jwt-{name}") for name in ("alice", "bob")}

    async def current_user(request: Request):
        return users[request.headers.get("X-Test-User", "alice")]

    for route in app.routes:
        for dependency in getattr(getattr(route, "dependant", None), "dependencies", []):
            if dependency.name == "user":
                app.dependency_overrides[dependency.call] = current_user
    app.dependency_overrides[get_task_service] = lambda: tasks
    app.dependency_overrides[get_session_manager] = lambda: SimpleNamespace(
        get_user_opensearch_client=lambda user_id, jwt: user_client
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            factory=factory,
            os=os_client,
            src=src,
            store=store,
            rec=rec,
            tasks=tasks,
            user_client=user_client,
            roles=role_calls,
            removed_roles=removed_roles,
            preflights=preflights,
            preflight_result=result_box,
            monkeypatch=monkeypatch,
            real_apply_role=real_apply_role,
            real_remove_role=real_remove_role,
        )
    await engine.dispose()


def _as(user: str) -> dict:
    return {"X-Test-User": user}


SOURCE_BODY = {
    "name": "Fixture",
    "bucket": "openrag-snapshots",
    "prefix": "scientists/",
    "access_key": "AKIATESTKEY",
    "secret_key": "s3cr3t-value",
}


# ── gate and status ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gated_routes_404_when_unavailable_but_status_stays_200(env):
    enable_feature(env.monkeypatch, enabled=False, reason="langflow_chat")

    status = await env.client.get(f"{PREFIX}/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is False and status.json()["reason"] == "langflow_chat"

    for method, path in (
        ("GET", "/sources"),
        ("GET", "/imports"),
        ("GET", "/datasets"),
        ("POST", "/sources"),
        ("DELETE", "/imports/x"),
    ):
        response = await env.client.request(
            method, PREFIX + path, json={} if method == "POST" else None
        )
        assert response.status_code == 404, (method, path)
    assert env.os.calls == [] and env.preflights == []


@pytest.mark.asyncio
async def test_status_reports_staging_and_security_capabilities(env):
    env.monkeypatch.setattr(svc.cfg, "get_snapshot_staging_type", lambda: "s3")
    body = (await env.client.get(f"{PREFIX}/status")).json()
    assert body == {
        "enabled": True,
        "reason": None,
        "staging_type": "s3",
        "security_managed": True,
        "private_supported": True,
    }

    enable_feature(env.monkeypatch, skip_security=True)
    body = (await env.client.get(f"{PREFIX}/status")).json()
    assert (body["security_managed"], body["private_supported"]) == (False, False)

    enable_feature(env.monkeypatch, ibm=True)
    assert (await env.client.get(f"{PREFIX}/status")).json()["private_supported"] is False


# ── sources ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_lifecycle_never_returns_or_stores_plain_secrets(env):
    created = await env.client.post(f"{PREFIX}/sources", json=SOURCE_BODY)
    assert created.status_code == 201
    source = created.json()
    assert source["has_credentials"] is True and source["prefix"] == "scientists"
    assert "access_key" not in source and "secret_key" not in source

    listed = await env.client.get(f"{PREFIX}/sources")
    patched = await env.client.patch(f"{PREFIX}/sources/{source['id']}", json={"name": "Renamed"})
    assert patched.status_code == 200 and patched.json()["name"] == "Renamed"
    assert patched.json()["has_credentials"] is True  # omitted keys are kept
    for response in (created, listed, patched):
        assert "AKIATESTKEY" not in response.text and "s3cr3t-value" not in response.text
    assert [s["id"] for s in listed.json()["sources"]] == [source["id"]]

    async with env.factory() as session:
        from db.repositories import SnapshotImportRepo

        (row,) = await SnapshotImportRepo(session).list_sources("alice")
    assert row.access_key_enc and row.secret_key_enc
    assert svc.decrypt_key(row.access_key_enc) == "AKIATESTKEY"

    # credentials can be rotated, but only as a pair
    half = await env.client.patch(
        f"{PREFIX}/sources/{source['id']}", json={"access_key": "only-one"}
    )
    assert (half.status_code, half.json()["code"]) == (400, "invalid_credentials")

    deleted = await env.client.delete(f"{PREFIX}/sources/{source['id']}")
    assert deleted.status_code == 200
    assert (await env.client.get(f"{PREFIX}/sources")).json() == {"sources": []}


@pytest.mark.asyncio
async def test_source_endpoint_policy_rejection_and_failed_connection(env):
    rejected = await env.client.post(
        f"{PREFIX}/sources", json={**SOURCE_BODY, "endpoint_url": "http://169.254.169.254/latest"}
    )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "endpoint_rejected" and rejected.json()["error"]

    credentials_only_half = await env.client.post(
        f"{PREFIX}/sources", json={**SOURCE_BODY, "secret_key": None}
    )
    assert credentials_only_half.json()["code"] == "invalid_credentials"

    async def failing_connection():
        raise svc.source_mod.SnapshotSourceError("the bucket does not exist")

    env.src.test_connection = failing_connection
    failed = await env.client.post(f"{PREFIX}/sources", json=SOURCE_BODY)
    assert (failed.status_code, failed.json()["code"]) == (400, "connection_failed")
    assert (await env.client.get(f"{PREFIX}/sources")).json() == {"sources": []}


@pytest.mark.asyncio
async def test_source_delete_blocked_while_imports_exist_and_other_users_get_404(env):
    await seed_source(env.factory)
    await seed_import(env.factory)

    assert (await env.client.delete(f"{PREFIX}/sources/src-1")).json()["code"] == "source_in_use"
    assert (
        await env.client.delete(f"{PREFIX}/sources/src-1", headers=_as("bob"))
    ).status_code == 404
    assert (
        await env.client.patch(f"{PREFIX}/sources/src-1", json={"name": "x"}, headers=_as("bob"))
    ).status_code == 404
    assert (
        await env.client.get(f"{PREFIX}/sources/src-1/snapshots", headers=_as("bob"))
    ).status_code == 404
    assert (await env.client.get(f"{PREFIX}/sources", headers=_as("bob"))).json() == {"sources": []}


@pytest.mark.asyncio
async def test_list_snapshots_and_preflight_passthrough(env):
    await seed_source(env.factory)
    snapshots = await env.client.get(f"{PREFIX}/sources/src-1/snapshots")
    assert snapshots.status_code == 200
    body = snapshots.json()
    assert body["repository_generation"] == 7
    assert body["snapshots"][0]["name"] == "snap-1"
    assert body["snapshots"][0]["indices"] == [
        {"name": "idx_a", "size_bytes": 10},
        {"name": "idx_b", "size_bytes": 10},
    ]

    env.preflight_result["result"] = make_preflight(
        blockers=[("version_incompatible", "created by Elasticsearch")],
        analyser=[
            (
                "idx_b",
                "index.analysis.filter.syn.synonyms_path",
                "analysis/s.txt",
                "index.analysis.filter.syn.synonyms",
            )
        ],
    )
    response = await env.client.post(
        f"{PREFIX}/sources/src-1/preflight",
        json={"snapshot": "snap-1", "indices": ["idx_a", "idx_b"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["blockers"] == [
        {"code": "version_incompatible", "message": "created by Elasticsearch", "index": None}
    ]
    assert body["analyser_files"][0]["inline_setting"].endswith(".synonyms")
    assert (body["staged_bytes"], body["restored_bytes"]) == (1000, 2000)
    assert body["indices"][0] == {"name": "idx_a", "created_version": "3.8.0", "doc_count": 5}
    call = env.preflights[-1]
    assert call["snapshot"] == "snap-1" and call["indices"] == ["idx_a", "idx_b"]
    assert (
        call["staging"] is env.store and call["max_import_bytes"] > 0 and call["os_admin"] is env.os
    )

    other = await env.client.post(
        f"{PREFIX}/sources/src-1/preflight",
        json={"snapshot": "snap-1", "indices": ["idx_a"]},
        headers=_as("bob"),
    )
    assert other.status_code == 404


# ── import creation ──────────────────────────────────────────────────────

IMPORT_BODY = {
    "source_id": "src-1",
    "snapshot": "snap-1",
    "indices": ["idx_b", "idx_a"],
    "name": "Scientists",
}


@pytest.mark.asyncio
async def test_create_import_enqueues_a_job_with_opaque_names(env):
    await seed_source(env.factory)
    response = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)

    assert response.status_code == 202
    payload = response.json()
    imported = payload["import"]
    assert imported["status"] == "staging" and imported["job"]["state"] == "queued"
    assert imported["source_indices"] == ["idx_a", "idx_b"]  # sorted: ordinal = position
    assert imported["is_owner"] is True and imported["shared"] is False
    slug = imported["slug"]
    assert [d["index_alias"] for d in imported["datasets"]] == [f"ds_{slug}_0", f"ds_{slug}_1"]
    assert [d["source_index"] for d in imported["datasets"]] == ["idx_a", "idx_b"]
    assert "idx_a" not in json.dumps([d["index_alias"] for d in imported["datasets"]])

    (task,) = env.tasks.created
    assert task["task_id"] == payload["task_id"] == imported["job"]["task_id"]
    assert (task["processor"].kind, task["processor"].import_id) == ("import", imported["id"])
    imp, _ = await load_import(env.factory, imported["id"])
    assert imp.os_principal == "alice-principal" and imp.analyser_inlines == {}


@pytest.mark.asyncio
async def test_create_import_rejects_blockers_with_422(env):
    await seed_source(env.factory)
    env.preflight_result["result"] = make_preflight(
        blockers=[("too_large", "import exceeds the limit")]
    )

    response = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)

    assert response.status_code == 422
    assert response.json()["blockers"] == [
        {"code": "too_large", "message": "import exceeds the limit", "index": None}
    ]
    assert env.tasks.created == []
    assert (await env.client.get(f"{PREFIX}/imports")).json() == {"imports": []}


@pytest.mark.asyncio
async def test_create_import_requires_analyser_files_to_match_the_discovered_refs(env):
    await seed_source(env.factory)
    ref = (
        "idx_b",
        "index.analysis.filter.syn.synonyms_path",
        "analysis/s.txt",
        "index.analysis.filter.syn.synonyms",
    )
    env.preflight_result["result"] = make_preflight(analyser=[ref])

    missing = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)
    assert (missing.status_code, missing.json()["code"]) == (422, "analyser_mismatch")

    forged = await env.client.post(
        f"{PREFIX}/imports",
        json={
            **IMPORT_BODY,
            "analyser_files": [
                {
                    "index": "idx_b",
                    "setting": "index.analysis.filter.syn.synonyms_path",
                    "content": "a,b",
                },
                {
                    "index": "idx_a",
                    "setting": "index.analysis.filter.x.synonyms_path",
                    "content": "x",
                },
            ],
        },
    )
    assert (forged.status_code, forged.json()["code"]) == (422, "analyser_mismatch")
    assert env.tasks.created == []

    ok = await env.client.post(
        f"{PREFIX}/imports",
        json={
            **IMPORT_BODY,
            "analyser_files": [
                {
                    "index": "idx_b",
                    "setting": "index.analysis.filter.syn.synonyms_path",
                    "content": "dna, deoxyribonucleic acid\n# comment",
                }
            ],
        },
    )
    assert ok.status_code == 202
    imp, _ = await load_import(env.factory, ok.json()["import"]["id"])
    assert imp.analyser_inlines == {
        "idx_b": {"index.analysis.filter.syn.synonyms": ["dna, deoxyribonucleic acid"]}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["skip", "ibm"])
async def test_private_imports_are_refused_when_opensearch_security_is_not_ours(env, mode):
    await seed_source(env.factory)
    enable_feature(env.monkeypatch, skip_security=mode == "skip", ibm=mode == "ibm")

    private = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)
    assert (private.status_code, private.json()["code"]) == (409, "private_not_supported")
    assert env.tasks.created == [] and env.preflights == []

    shared = await env.client.post(f"{PREFIX}/imports", json={**IMPORT_BODY, "shared": True})
    assert shared.status_code == 202
    imp, _ = await load_import(env.factory, shared.json()["import"]["id"])
    assert imp.shared is True and imp.os_principal is None
    if mode == "skip":
        # operators provision the role themselves: the JSON they need is returned
        role_json = shared.json()["import"]["role_json"]
        assert role_json["role_name"] == f"openrag_ds_{imp.slug}"


@pytest.mark.asyncio
async def test_import_count_limit_and_staging_space_are_enforced(env):
    await seed_source(env.factory)
    env.monkeypatch.setattr(svc.cfg, "get_snapshot_max_imports_per_user", lambda: 1)
    env.store.free = 500  # preflight says 1000 bytes are needed

    no_space = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)
    assert (no_space.status_code, no_space.json()["code"]) == (409, "insufficient_disk_staging")

    env.store.free = None
    assert (await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)).status_code == 202
    limited = await env.client.post(f"{PREFIX}/imports", json=IMPORT_BODY)
    assert (limited.status_code, limited.json()["code"]) == (409, "import_limit")


# ── dataset mapping, activation, sharing ─────────────────────────────────


@pytest.mark.asyncio
async def test_dataset_patch_validates_field_maps_and_names(env):
    await seed_source(env.factory)
    await seed_import(env.factory)
    url = f"{PREFIX}/imports/imp-1/datasets/imp-1-ds0"

    ok = await env.client.patch(
        url,
        json={
            "display_name": "Scientists",
            "description": "People",
            "field_map": {"text_fields": ["body"], "title_field": "title", "url_field": None},
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert (body["display_name"], body["description"]) == ("Scientists", "People")
    assert body["field_map"]["text_fields"] == ["body"]
    assert {f["name"] for f in body["fields"]} >= {"title", "body", "url"}

    bad = await env.client.patch(
        url, json={"field_map": {"text_fields": ["nope"], "title_field": None, "url_field": None}}
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_dataset")
    assert bad.json()["messages"]

    assert (
        await env.client.patch(url, json={"display_name": "x"}, headers=_as("bob"))
    ).status_code == 404
    assert (
        await env.client.patch(
            f"{PREFIX}/imports/imp-1/datasets/missing", json={"display_name": "x"}
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_activate_probes_with_the_users_token_and_goes_active(env):
    await seed_source(env.factory)
    await seed_import(env.factory)

    response = await env.client.post(f"{PREFIX}/imports/imp-1/activate")

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert env.roles == [{"slug": SLUG, "principal": "alice", "shared": False}]
    assert [s[0] for s in env.user_client.searches] == [f"ds_{SLUG}_0", f"ds_{SLUG}_1"]
    assert all(body == {"size": 0} for _, body in env.user_client.searches)


@pytest.mark.asyncio
async def test_activate_probe_failure_keeps_review_and_returns_role_json(env):
    await seed_source(env.factory)
    await seed_import(env.factory)
    env.user_client.deny = True

    response = await env.client.post(f"{PREFIX}/imports/imp-1/activate")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "role_not_provisioned"
    assert body["role_json"] == {"role_name": f"openrag_ds_{SLUG}"}
    imp, _ = await load_import(env.factory)
    assert imp.status == "review"
    assert env.removed_roles == [SLUG]  # the mapping applied for the probe is rolled back (B2)


@pytest.mark.asyncio
async def test_activate_under_skip_makes_no_security_calls_and_returns_the_role_json(env):
    enable_feature(env.monkeypatch, skip_security=True)
    env.monkeypatch.setattr(roles, "apply_role", env.real_apply_role)  # the real, SKIP-aware writer
    env.monkeypatch.setattr(roles, "remove_role", env.real_remove_role)  # ... and remover
    await seed_source(env.factory)
    await seed_import(env.factory, shared=True)
    env.user_client.deny = True

    response = await env.client.post(f"{PREFIX}/imports/imp-1/activate")

    assert response.status_code == 409 and response.json()["code"] == "role_not_provisioned"
    role_json = response.json()["role_json"]
    assert role_json["role_name"] == f"openrag_ds_{SLUG}"
    assert "openrag_user" in json.dumps(role_json)  # shared => backend role mapping
    assert env.os.calls and all(
        c[0] in ("get_mapping", "get_alias") for c in env.os.calls
    )  # reads only

    env.user_client.deny = False  # operator provisioned it out of band
    assert (await env.client.post(f"{PREFIX}/imports/imp-1/activate")).json()["status"] == "active"


@pytest.mark.asyncio
async def test_activate_rejects_invalid_field_maps(env):
    await seed_source(env.factory)
    await seed_import(
        env.factory, field_map={"text_fields": ["ghost"], "title_field": None, "url_field": None}
    )

    response = await env.client.post(f"{PREFIX}/imports/imp-1/activate")

    assert (response.status_code, response.json()["code"]) == (422, "field_map_invalid")
    assert response.json()["datasets"][0]["messages"]
    assert env.roles == [] and env.user_client.searches == []


@pytest.mark.asyncio
async def test_share_and_unshare_update_the_role_of_an_active_import(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="active")

    shared = await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": True})
    assert shared.status_code == 200 and shared.json()["shared"] is True
    unshared = await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": False})
    assert unshared.status_code == 200 and unshared.json()["shared"] is False
    assert [c["shared"] for c in env.roles] == [True, False]
    assert env.roles[1]["principal"] == "alice"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["skip", "ibm"])
async def test_unsharing_is_refused_when_private_is_unsupported(env, mode):
    enable_feature(env.monkeypatch, skip_security=mode == "skip", ibm=mode == "ibm")
    await seed_source(env.factory)
    await seed_import(env.factory, status="active", shared=True)

    response = await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": False})

    assert (response.status_code, response.json()["code"]) == (409, "private_not_supported")
    assert env.roles == []
    imp, _ = await load_import(env.factory)
    assert imp.shared is True


@pytest.mark.asyncio
async def test_ownership_is_enforced_with_404_and_shared_imports_are_read_only(env):
    await seed_source(env.factory)
    await seed_import(env.factory, id="mine", slug="aaaaaaaaaa", status="active")
    await seed_import(env.factory, id="theirs", slug="bbbbbbbbbb", status="active", shared=True)

    # bob cannot see alice's private import in any form
    for method, path, body in (
        ("GET", "/imports/mine", None),
        ("POST", "/imports/mine/activate", None),
        ("POST", "/imports/mine/share", {"shared": True}),
        ("DELETE", "/imports/mine", None),
        ("POST", "/imports/mine/reimport", {"snapshot": "snap-1"}),
        ("POST", "/imports/mine/reimport/preflight", {"snapshot": "snap-1"}),
        ("PATCH", "/imports/mine/datasets/mine-ds0", {"display_name": "x"}),
    ):
        response = await env.client.request(method, PREFIX + path, json=body, headers=_as("bob"))
        assert response.status_code == 404, (method, path)
    listed = (await env.client.get(f"{PREFIX}/imports", headers=_as("bob"))).json()["imports"]
    assert [i["id"] for i in listed] == ["theirs"]

    # a shared import is visible to bob but only the owner can mutate it
    visible = await env.client.get(f"{PREFIX}/imports/theirs", headers=_as("bob"))
    assert visible.status_code == 200 and visible.json()["is_owner"] is False
    assert visible.json()["role_json"] is None
    assert (
        await env.client.post(
            f"{PREFIX}/imports/theirs/share", json={"shared": False}, headers=_as("bob")
        )
    ).status_code == 404
    assert (
        await env.client.post(f"{PREFIX}/imports/theirs/activate", headers=_as("bob"))
    ).status_code == 404
    assert env.tasks.cancelled == [] and env.tasks.created == []


@pytest.mark.asyncio
async def test_datasets_route_lists_visible_active_datasets(env):
    await seed_source(env.factory)
    await seed_import(env.factory, id="mine", slug="aaaaaaaaaa", status="active")
    await seed_import(
        env.factory,
        id="theirs",
        slug="bbbbbbbbbb",
        status="active",
        owner="bob",
        shared=True,
        principal="bob",
    )
    await seed_import(
        env.factory, id="hidden", slug="cccccccccc", status="active", owner="bob", principal="bob"
    )
    await seed_import(env.factory, id="review", slug="dddddddddd", status="review")

    body = (await env.client.get(f"{PREFIX}/datasets")).json()["datasets"]

    assert {d["import_id"] for d in body} == {"mine", "theirs"}
    mine = next(d for d in body if d["id"] == "mine-ds0")
    assert mine == {
        "id": "mine-ds0",
        "import_id": "mine",
        "import_name": "Import mine",
        "display_name": "idx_a",
        "description": "",
        "source_index": "idx_a",
        "shared": False,
        "is_owner": True,
    }
    assert next(d for d in body if d["import_id"] == "theirs")["is_owner"] is False


# ── re-import and delete ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reimport_preflight_uses_the_same_indices_and_replaced_bytes(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="active")

    response = await env.client.post(
        f"{PREFIX}/imports/imp-1/reimport/preflight", json={"snapshot": "snap-2"}
    )

    assert response.status_code == 200
    call = env.preflights[-1]
    assert call["indices"] == ["idx_a", "idx_b"] and call["replaced_bytes"] == 1000
    assert "uuid-snap-1" not in call["existing_snapshot_uuids"]  # the import being replaced


@pytest.mark.asyncio
async def test_concurrent_reimport_is_rejected_with_job_in_progress(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="active")

    first = await env.client.post(f"{PREFIX}/imports/imp-1/reimport", json={"snapshot": "snap-2"})
    second = await env.client.post(f"{PREFIX}/imports/imp-1/reimport", json={"snapshot": "snap-3"})

    assert first.status_code == 202
    assert first.json()["import"]["job"] == {
        "state": "queued",
        "kind": "reimport",
        "error": None,
        "task_id": first.json()["task_id"],
    }
    assert (second.status_code, second.json()["code"]) == (409, "job_in_progress")
    assert len(env.tasks.created) == 1
    assert (env.tasks.created[0]["processor"].kind, env.tasks.created[0]["processor"].snapshot) == (
        "reimport",
        "snap-2",
    )
    # other mutations are refused too while the job runs
    assert (await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": True})).json()[
        "code"
    ] == "job_in_progress"
    assert (await env.client.post(f"{PREFIX}/imports/imp-1/activate")).json()[
        "code"
    ] == "job_in_progress"


@pytest.mark.asyncio
async def test_failed_reimport_can_be_retried(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="active", job_state="failed", job_kind="reimport")

    assert (
        await env.client.post(f"{PREFIX}/imports/imp-1/reimport", json={"snapshot": "snap-2"})
    ).status_code == 202

    queued = env.tasks.created[-1]["processor"]
    assert (
        queued.snapshot_uuid == "uuid-snap-1"
    )  # the identity preflight admitted travels with the job (B12)
    imp, _ = await load_import(env.factory)
    assert imp.attempt_generation == 2  # reserved at admission, above the serving generation (B5)


@pytest.mark.asyncio
async def test_import_awaiting_recovery_refuses_jobs_but_still_allows_revoking_visibility(env):
    await seed_source(env.factory)
    await seed_import(
        env.factory, status="active", job_state="recovery", job_kind="reimport", shared=True
    )
    await _set_import(env.factory, attempt_generation=2)

    async def failing_delete(os_admin, names):
        raise restore.RestoreError("opensearch unavailable")

    env.monkeypatch.setattr(restore, "delete_indices", failing_delete)

    retry = await env.client.post(f"{PREFIX}/imports/imp-1/reimport", json={"snapshot": "snap-2"})
    activate = await env.client.post(f"{PREFIX}/imports/imp-1/activate")
    patch = await env.client.patch(
        f"{PREFIX}/imports/imp-1/datasets/imp-1-ds0", json={"display_name": "x"}
    )
    unshare = await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": False})

    assert [r.json()["code"] for r in (retry, activate, patch)] == ["recovery_required"] * 3
    assert [r.status_code for r in (retry, activate, patch)] == [409, 409, 409]
    assert unshare.status_code == 200 and unshare.json()["job"]["state"] == "recovery"
    assert [c["shared"] for c in env.roles] == [False]  # the role was narrowed to the owner
    assert env.tasks.created == []
    # delete stays possible from recovery
    assert (await env.client.delete(f"{PREFIX}/imports/imp-1")).status_code == 202


async def _set_import(factory, **values):
    from db.repositories import SnapshotImportRepo

    async with factory() as session:
        await SnapshotImportRepo(session).update_import("imp-1", **values)
        await session.commit()


@pytest.mark.asyncio
async def test_reimport_of_an_unrestored_import_is_refused(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="failed", job_state="failed")

    response = await env.client.post(
        f"{PREFIX}/imports/imp-1/reimport", json={"snapshot": "snap-2"}
    )

    assert (response.status_code, response.json()["code"]) == (409, "not_ready")


@pytest.mark.asyncio
async def test_delete_cancels_the_running_task_then_enqueues_the_delete_job(env):
    await seed_source(env.factory)
    await seed_import(
        env.factory,
        status="active",
        job_state="running",
        job_kind="reimport",
        task_id="running-task",
    )

    response = await env.client.delete(f"{PREFIX}/imports/imp-1")

    assert response.status_code == 202
    assert env.tasks.cancelled == [("alice", "running-task")]
    imported = response.json()["import"]
    assert (imported["status"], imported["job"]["kind"], imported["job"]["state"]) == (
        "deleting",
        "delete",
        "queued",
    )
    (task,) = env.tasks.created
    assert (task["processor"].kind, task["processor"].import_id) == ("delete", "imp-1")
    assert imported["job"]["task_id"] == task["task_id"] != "running-task"
    # a deleting import accepts no further mutations
    assert (await env.client.post(f"{PREFIX}/imports/imp-1/share", json={"shared": True})).json()[
        "code"
    ] == "deleting"


@pytest.mark.asyncio
async def test_delete_of_an_idle_import_does_not_cancel_anything(env):
    await seed_source(env.factory)
    await seed_import(env.factory, status="review")

    response = await env.client.delete(f"{PREFIX}/imports/imp-1")

    assert response.status_code == 202 and env.tasks.cancelled == []
    assert env.tasks.created[0]["processor"].kind == "delete"


def test_routes_are_internal_and_only_status_is_ungated():
    app = FastAPI()
    OpenSearchSnapshotConnector.register_routes(app)
    routes = {
        (m, r.path): r
        for r in app.routes
        if hasattr(r, "methods") and r.path.startswith(PREFIX)
        for m in r.methods
    }
    assert {(m, p.removeprefix(PREFIX)) for m, p in routes} == {
        ("GET", "/status"),
        ("POST", "/sources"),
        ("GET", "/sources"),
        ("PATCH", "/sources/{source_id}"),
        ("DELETE", "/sources/{source_id}"),
        ("GET", "/sources/{source_id}/snapshots"),
        ("POST", "/sources/{source_id}/preflight"),
        ("POST", "/imports"),
        ("GET", "/imports"),
        ("GET", "/imports/{import_id}"),
        ("PATCH", "/imports/{import_id}/datasets/{dataset_id}"),
        ("POST", "/imports/{import_id}/activate"),
        ("POST", "/imports/{import_id}/share"),
        ("POST", "/imports/{import_id}/reimport/preflight"),
        ("POST", "/imports/{import_id}/reimport"),
        ("DELETE", "/imports/{import_id}"),
        ("GET", "/datasets"),
    }
    assert all("internal" in r.tags for r in routes.values())
    gated = {p.removeprefix(PREFIX) for (m, p), r in routes.items() if r.dependencies}
    assert "/status" not in gated and "/imports" in gated and "/datasets" in gated
    assert endpoint_policy and restore  # engine modules the routes rely on are importable
