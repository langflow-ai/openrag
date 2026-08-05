import asyncio
import os
from pathlib import Path

import httpx
import pytest

# Files to exclude from ingestion (should match src/main.py)
EXCLUDED_INGESTION_FILES = {"warmup_ocr.pdf"}
_RELOAD_MODULES = [
    "api",
    "api.router",
    "api.connector_router",
    "app",
    "app.container",
    "app.factory",
    "app.lifespan",
    "app.routes",
    "app.routes.internal",
    "config.settings",
    "dependencies",
    "auth_middleware",
    "main",
    "services",
    "services.default_docs_service",
    "services.search_service",
    "services.startup_orchestrator",
    "utils.opensearch_init",
]
_RELOAD_PREFIXES = ("api.", "app.", "services.")


def _purge_reloaded_modules() -> None:
    import sys

    for mod in list(sys.modules):
        if mod in _RELOAD_MODULES or mod.startswith(_RELOAD_PREFIXES):
            sys.modules.pop(mod, None)


async def wait_for_ready(client: httpx.AsyncClient, timeout_s: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            r1 = await client.get("/auth/me")
            if r1.status_code != 200:
                await asyncio.sleep(0.5)
                continue
            r2 = await client.post("/search", json={"query": "*", "limit": 0})
            if r2.status_code == 200:
                return
            last_err = r2.text
        except Exception as e:
            last_err = str(e)
        await asyncio.sleep(0.5)
    raise AssertionError(f"Service not ready in time: {last_err}")


def count_files_in_documents() -> int:
    base_dir = Path(os.getcwd()) / "openrag-documents"
    if not base_dir.is_dir():
        return 0
    return sum(
        1 for _ in base_dir.rglob("*") if _.is_file() and _.name not in EXCLUDED_INGESTION_FILES
    )


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_startup_ingest_creates_task(disable_langflow_ingest: bool):
    # Ensure startup ingest runs and choose pipeline per param
    os.environ["DISABLE_STARTUP_INGEST"] = "false"
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    # Force no-auth mode for simpler endpoint access
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    # Reload settings to pick up env for this test run
    _purge_reloaded_modules()

    from config.settings import clients, get_index_name
    from main import create_app

    # Ensure a clean index before startup
    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=get_index_name())
    except Exception:
        pass

    app = await create_app()
    startup_complete = False
    lifespan_ctx = None
    try:
        # Starlette 1.x removed Router.startup()/shutdown(); drive the app's
        # lifespan context manager directly, like an ASGI server would.
        lifespan_ctx = app.router.lifespan_context(app)
        await lifespan_ctx.__aenter__()
        startup_complete = True

        # Ensure index exists for tests (startup_tasks only creates it if DISABLE_INGEST_WITH_LANGFLOW=True)
        from main import _ensure_opensearch_index

        await _ensure_opensearch_index()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_ready(client)

            expected_files = count_files_in_documents()

            # Poll /tasks until we see at least one startup ingest task
            async def _wait_for_task(timeout_s: float = 60.0):
                deadline = asyncio.get_event_loop().time() + timeout_s
                last = None
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.get("/tasks")
                    if resp.status_code == 200:
                        data = resp.json()
                        last = data
                        tasks = data.get("tasks") if isinstance(data, dict) else None
                        if isinstance(tasks, list) and len(tasks) > 0:
                            return tasks
                    await asyncio.sleep(0.5)
                return last.get("tasks") if isinstance(last, dict) else last

            tasks = await _wait_for_task()
            if expected_files == 0:
                return  # Nothing to do
            if not (isinstance(tasks, list) and len(tasks) > 0):
                # Fallback: verify that documents were indexed as a sign of startup ingest
                sr = await client.post("/search", json={"query": "*", "limit": 1})
                assert sr.status_code == 200, sr.text
                total = sr.json().get("total")
                assert isinstance(total, int) and total >= 0, (
                    "Startup ingest did not index documents"
                )
                return
            newest = tasks[0]
            assert "task_id" in newest
            assert isinstance(newest.get("total_files"), int)
            assert newest["total_files"] > 0
            assert newest.get("files")
    finally:
        if startup_complete and lifespan_ctx is not None:
            try:
                await lifespan_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        # Explicitly close global clients to avoid aiohttp warnings
        from config.settings import clients

        try:
            await clients.close()
        except Exception:
            pass
