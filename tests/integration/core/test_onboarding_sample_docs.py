import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
]


_RELOAD_MODULES = [
    "api.router",
    "api.connector_router",
    "api.settings.endpoints",
    "api.settings.helpers",
    "api.settings.langflow_sync",
    "api.settings",
    "api",
    "app.container",
    "app.routes.internal",
    "app.routes.public_v1",
    "app.routes",
    "app.factory",
    "app.lifespan",
    "auth_middleware",
    "config.config_manager",
    "config.settings",
    "dependencies",
    "main",
    "services",
    "services.default_docs_service",
    "services.search_service",
    "services.startup_orchestrator",
    "utils.opensearch_init",
]

_EXCLUDED_DEFAULT_DOCS = {"warmup_ocr.pdf"}


def _reload_openrag_modules() -> None:
    for module_name in _RELOAD_MODULES:
        sys.modules.pop(module_name, None)


async def _require_langflow_ready() -> None:
    langflow_url = os.getenv("LANGFLOW_URL", "http://localhost:7860").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{langflow_url}/health")
    except Exception as exc:
        pytest.skip(f"Langflow is required for onboarding integration tests: {exc}")

    if response.status_code != 200:
        pytest.skip(
            "Langflow is required for onboarding integration tests: "
            f"{langflow_url}/health returned {response.status_code}"
        )


@pytest_asyncio.fixture
async def isolated_onboarding_docs_workspace(tmp_path: Path, monkeypatch):
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is required for onboarding sample-doc ingestion")

    docs_dir = Path(__file__).resolve().parents[3] / "openrag-documents"
    expected_filenames = sorted(
        path.name
        for path in docs_dir.rglob("*")
        if path.is_file() and path.name not in _EXCLUDED_DEFAULT_DOCS
    )
    if not expected_filenames:
        pytest.fail(f"No default docs found in {docs_dir}")

    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    keys_dir = tmp_path / "keys"
    for directory in (config_dir, data_dir, keys_dir):
        directory.mkdir()

    index_name = f"documents_onboarding_sample_{uuid4().hex}"
    db_path = tmp_path / "openrag.db"

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OPENRAG_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv("OPENRAG_DATA_PATH", str(data_dir))
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(docs_dir))
    monkeypatch.setenv("OPENRAG_KEYS_PATH", str(keys_dir))
    monkeypatch.setenv("OPENSEARCH_INDEX_NAME", index_name)
    monkeypatch.setenv("INGEST_SAMPLE_DATA", "true")
    monkeypatch.setenv("DEFAULT_DOCS_INGEST_SOURCE", "files")
    monkeypatch.setenv("DISABLE_INGEST_WITH_LANGFLOW", "false")
    monkeypatch.setenv("DISABLE_STARTUP_INGEST", "true")
    monkeypatch.setenv("FETCH_OPENRAG_DOCS_AT_STARTUP", "false")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setenv("OPENRAG_NOAUTH_ROLE", "admin")
    monkeypatch.setenv("OPENRAG_RBAC_ENFORCE", "true")

    from db.engine import dispose_engine
    from dependencies import invalidate_user_ensured_cache

    await dispose_engine()
    invalidate_user_ensured_cache()
    _reload_openrag_modules()
    await _require_langflow_ready()

    try:
        yield {
            "index_name": index_name,
            "expected_filenames": expected_filenames,
        }
    finally:
        try:
            from config.settings import clients

            if clients.opensearch is not None:
                await clients.opensearch.indices.delete(
                    index=index_name,
                    ignore_unavailable=True,
                )
            await clients.close()
        except Exception:
            pass
        await dispose_engine()
        invalidate_user_ensured_cache()
        _reload_openrag_modules()


async def _wait_for_task(task_service, task_id: str, timeout_s: float = 900.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_status = None
    while asyncio.get_event_loop().time() < deadline:
        last_status = task_service.get_task_status("anonymous", task_id)
        if last_status and last_status.get("status") in {"completed", "failed"}:
            return last_status
        await asyncio.sleep(0.5)
    raise AssertionError(f"Sample-doc ingestion task did not finish: {last_status}")


async def _post_onboarding_when_langflow_ready(
    client: httpx.AsyncClient,
    payload: dict[str, str],
    timeout_s: float = 60.0,
) -> httpx.Response:
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_response = None
    while asyncio.get_event_loop().time() < deadline:
        response = await client.post("/onboarding", json=payload)
        if response.status_code != 503 or "Langflow service" not in response.text:
            return response
        last_response = response
        await asyncio.sleep(1.0)
    assert last_response is not None
    return last_response


async def test_onboarding_ingests_sample_docs_and_creates_openrag_docs_filter(
    isolated_onboarding_docs_workspace,
):
    from config.settings import clients, config_manager
    from db.migrations_runtime import run_alembic_upgrade_async
    from main import create_app

    await run_alembic_upgrade_async("head")

    app = await create_app()
    startup_complete = False
    try:
        await app.router.startup()
        startup_complete = True

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await _post_onboarding_when_langflow_ready(
                client,
                {
                    "openai_api_key": os.environ["OPENAI_API_KEY"],
                    "llm_provider": "openai",
                    "embedding_provider": "openai",
                    "embedding_model": "text-embedding-3-small",
                    "llm_model": "gpt-4o-mini",
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["sample_data_ingested"] is True
        assert payload["task_id"]
        assert payload["openrag_docs_filter_id"]

        task_status = await _wait_for_task(app.state.services["task_service"], payload["task_id"])
        assert task_status["status"] == "completed"
        assert task_status["successful_files"] == len(
            isolated_onboarding_docs_workspace["expected_filenames"]
        )
        assert task_status["failed_files"] == 0

        config = config_manager.get_config()
        assert config.onboarding.openrag_docs_filter_id == payload["openrag_docs_filter_id"]
        assert config.onboarding.openrag_docs_ingested_version

        await clients.opensearch.indices.refresh(
            index=isolated_onboarding_docs_workspace["index_name"]
        )
        search_response = await clients.opensearch.search(
            index=isolated_onboarding_docs_workspace["index_name"],
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"connector_type": "openrag_docs"}},
                            {"term": {"is_sample_data": "true"}},
                        ]
                    }
                },
                "aggs": {"filenames": {"terms": {"field": "filename", "size": 100}}},
                "size": 0,
            },
        )
        total = search_response.get("hits", {}).get("total", {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        assert total_value > 0, "Expected onboarding sample document chunks to be indexed"

        filename_buckets = (
            search_response.get("aggregations", {}).get("filenames", {}).get("buckets", [])
        )
        indexed_filenames = {bucket["key"] for bucket in filename_buckets}
        assert set(isolated_onboarding_docs_workspace["expected_filenames"]).issubset(
            indexed_filenames
        )
        assert indexed_filenames.isdisjoint(_EXCLUDED_DEFAULT_DOCS)
    finally:
        if startup_complete:
            await app.router.shutdown()
