"""End-to-end: import an OpenSearch snapshot from S3 and search it.

Drives a running OpenRAG backend over HTTP and checks OpenSearch directly with
per-user JWTs, so privacy is proven by OpenSearch itself, not by the registry.

Prerequisites (skipped unless ``OPENRAG_SNAPSHOT_E2E=1``):
  * ``make snapshot-fixture`` (MinIO on :9100 with snapshots scientists-v1/-v2).
  * OpenRAG OpenSearch from docker-compose (``path.repo`` + staging bind mount)
    and the backend on the host, in no-auth mode, with
    ``OPENRAG_SNAPSHOT_IMPORT_ENABLED=true``, ``DISABLE_CHAT_WITH_LANGFLOW=true``,
    ``OPENRAG_STORAGE_MODE=db`` and ``OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS=localhost:9100``.
  * The backend's ``keys/`` (same checkout) so minted JWTs validate in OpenSearch.
  * A documents index with the onboarded embedding field (ingest one document
    first) so ``/v1/search`` can query documents and datasets together.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
    pytest.mark.skipif(
        os.getenv("OPENRAG_SNAPSHOT_E2E") != "1",
        reason="set OPENRAG_SNAPSHOT_E2E=1 with the snapshot fixture and a running backend",
    ),
]

BACKEND = os.getenv("OPENRAG_E2E_BACKEND_URL", "http://localhost:8000")
API = f"{BACKEND}/connectors/opensearch_snapshot"
ROOT = Path(__file__).resolve().parents[3]
SYNONYMS = (ROOT / "scripts/snapshot_fixture/analysis/field_synonyms.txt").read_text()
SOURCE = {
    "name": f"e2e-{uuid4().hex[:6]}",
    "endpoint_url": os.getenv("SNAPSHOT_S3_ENDPOINT", "http://localhost:9100"),
    "region": "us-east-1",
    "bucket": "openrag-snapshots",
    "prefix": "scientists",
    "access_key": os.getenv("SNAPSHOT_S3_ACCESS_KEY", "snapshotadmin"),
    "secret_key": os.getenv("SNAPSHOT_S3_SECRET_KEY", "snapshotadmin123"),
    "path_style": True,
}
INDICES = ["famous_scientists", "scientific_discoveries"]
SETTING = "index.analysis.filter.field_synonyms.synonyms_path"


async def _wait_for(
    http: httpx.AsyncClient, import_id: str, done: set[str], timeout_s: float = 300
):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = await http.get(f"{API}/imports/{import_id}")
        if resp.status_code == 404 and "gone" in done:
            return None
        body = resp.json()
        if body["job"]["state"] in {"failed", "cancelled"}:
            pytest.fail(f"import job failed: {body['job']}")
        if body["status"] in done and body["job"]["state"] == "idle":
            return body
        await asyncio.sleep(1)
    pytest.fail(f"import {import_id} did not reach {done} in {timeout_s}s")


async def _user_search(user_id: str, index: str, body: dict) -> tuple[int, list[dict]]:
    """Search as ``user_id`` with an OpenRAG-signed OpenSearch JWT."""
    from opensearchpy.exceptions import TransportError

    from config.settings import clients
    from session_manager import SessionManager, User

    token = SessionManager("e2e").create_opensearch_jwt_token(
        User(user_id=user_id, email=f"{user_id}@example.com", name=user_id), ttl_seconds=120
    )
    client = clients.create_user_opensearch_client(token)
    try:
        resp = await client.search(index=index, body=body)
        return 200, [hit["_source"] for hit in resp["hits"]["hits"]]
    except TransportError as exc:
        return int(exc.status_code), []
    finally:
        await client.close()


def _admin():
    from opensearchpy import AsyncOpenSearch
    from opensearchpy._async.http_aiohttp import AIOHttpConnection

    from config.settings import (
        OPENSEARCH_HOST,
        OPENSEARCH_PASSWORD,
        OPENSEARCH_PORT,
        OPENSEARCH_USERNAME,
    )

    return AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        connection_class=AIOHttpConnection,
        scheme="https",
        use_ssl=True,
        verify_certs=False,
        ssl_assert_fingerprint=None,
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
    )


async def test_snapshot_import_lifecycle():
    owner = "anonymous"  # no-auth mode: every HTTP call is the anonymous user
    other = f"user-b-{uuid4().hex[:8]}"
    synonym_query = {
        "query": {"match": {"description": "deoxyribonucleic acid"}},
        "_source": ["title"],
    }

    async with httpx.AsyncClient(timeout=60) as http:
        status = (await http.get(f"{API}/status")).json()
        assert status["enabled"], status

        source = (await http.post(f"{API}/sources", json=SOURCE)).json()
        assert "secret_key" not in source and source["has_credentials"]
        snapshots = (await http.get(f"{API}/sources/{source['id']}/snapshots")).json()
        assert {"scientists-v1", "scientists-v2"} <= {s["name"] for s in snapshots["snapshots"]}

        preflight = (
            await http.post(
                f"{API}/sources/{source['id']}/preflight",
                json={"snapshot": "scientists-v1", "indices": INDICES},
            )
        ).json()
        assert preflight["ok"], preflight
        assert [(r["index"], r["setting"]) for r in preflight["analyser_files"]] == [
            ("scientific_discoveries", SETTING)
        ]

        base = {
            "source_id": source["id"],
            "snapshot": "scientists-v1",
            "indices": INDICES,
            "name": "E2E scientists",
        }
        missing = await http.post(f"{API}/imports", json={**base, "analyser_files": []})
        assert missing.status_code == 422, missing.text

        created = await http.post(
            f"{API}/imports",
            json={
                **base,
                "analyser_files": [
                    {"index": "scientific_discoveries", "setting": SETTING, "content": SYNONYMS}
                ],
            },
        )
        assert created.status_code == 202, created.text
        import_id = created.json()["import"]["id"]
        imp = await _wait_for(http, import_id, {"review"})
        by_index = {d["source_index"]: d for d in imp["datasets"]}
        assert by_index["famous_scientists"]["doc_count"] == 30
        assert by_index["scientific_discoveries"]["doc_count"] == 21
        assert by_index["famous_scientists"]["field_map"]["text_fields"]
        slug = imp["slug"]
        # Physical names never carry the source index name.
        assert {d["index_alias"] for d in imp["datasets"]} == {f"ds_{slug}_0", f"ds_{slug}_1"}

        imp = (await http.post(f"{API}/imports/{import_id}/activate")).json()
        assert imp["status"] == "active", imp
        discoveries = by_index["scientific_discoveries"]["index_alias"]

        # Private: the owner reads (and the inlined synonym file works); others are refused.
        code, hits = await _user_search(owner, discoveries, synonym_query)
        assert code == 200 and [h["title"] for h in hits] == ["Photo 51"]
        assert (await _user_search(other, discoveries, synonym_query))[0] == 403
        assert (await _user_search(other, f"{discoveries}_g1", synonym_query))[0] == 403

        assert (await http.post(f"{API}/imports/{import_id}/share", json={"shared": True})).json()[
            "shared"
        ]
        assert (await _user_search(other, discoveries, synonym_query))[0] == 200
        assert not (
            await http.post(f"{API}/imports/{import_id}/share", json={"shared": False})
        ).json()["shared"]
        assert (await _user_search(other, discoveries, synonym_query))[0] == 403

        # Public API: dataset hits are merged and tagged; datasets: [] excludes them.
        key = (await http.post(f"{BACKEND}/keys", json={"name": "snapshot-e2e"})).json()["api_key"]
        headers = {"X-API-Key": key}
        results = (
            await http.post(
                f"{BACKEND}/v1/search",
                headers=headers,
                json={"query": "deoxyribonucleic acid", "limit": 10},
            )
        ).json()["results"]
        tagged = [r for r in results if r.get("dataset")]
        assert any(
            r["dataset"]["id"] == by_index["scientific_discoveries"]["id"] for r in tagged
        ), results
        assert {"filename", "text", "score", "page", "mimetype"} <= set(results[0])
        none = (
            await http.post(
                f"{BACKEND}/v1/search",
                headers=headers,
                json={"query": "deoxyribonucleic acid", "limit": 10, "datasets": []},
            )
        ).json()["results"]
        assert not [r for r in none if r.get("dataset")]

        # Re-import a newer snapshot: one alias swap, previous generation removed.
        pre = (
            await http.post(
                f"{API}/imports/{import_id}/reimport/preflight", json={"snapshot": "scientists-v2"}
            )
        ).json()
        assert pre["ok"], pre
        started = await http.post(
            f"{API}/imports/{import_id}/reimport",
            json={
                "snapshot": "scientists-v2",
                "analyser_files": [
                    {"index": "scientific_discoveries", "setting": SETTING, "content": SYNONYMS}
                ],
            },
        )
        assert started.status_code == 202, started.text
        imp = await _wait_for(http, import_id, {"active"})
        assert imp["generation"] == 2 and imp["snapshot_name"] == "scientists-v2"
        admin = _admin()
        try:
            aliases = await admin.indices.get_alias(name=f"ds_{slug}_*")
            assert sorted(aliases) == [f"ds_{slug}_0_g2", f"ds_{slug}_1_g2"]
            assert not await admin.indices.exists(index=f"ds_{slug}_0_g1")
            assert (await _user_search(owner, discoveries, synonym_query))[1][0][
                "title"
            ] == "Photo 51"

            deleted = await http.delete(f"{API}/imports/{import_id}")
            assert deleted.status_code == 202, deleted.text
            await _wait_for(http, import_id, {"gone"})
            assert not await admin.indices.exists(index=f"ds_{slug}_*", allow_no_indices=False)
            roles = await admin.transport.perform_request("GET", "/_plugins/_security/api/roles")
            assert f"openrag_ds_{slug}" not in roles
            repos = await admin.snapshot.get_repository()
            assert not [name for name in repos if slug in name]
        finally:
            await admin.close()
        assert (await http.delete(f"{API}/sources/{source['id']}")).status_code in (200, 204)
