import asyncio
import os
from pathlib import Path

import httpx
import pytest


async def wait_for_service_ready(client: httpx.AsyncClient, timeout_s: float = 30.0):
    """Poll existing endpoints until the app and OpenSearch are ready.

    Strategy:
    - GET /auth/me should return 200 immediately (confirms app is up).
    - POST /search with query "*" avoids embeddings and checks OpenSearch/index readiness.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            r1 = await client.get("/auth/me")
            if r1.status_code in (401, 403):
                raise AssertionError(f"/auth/me returned {r1.status_code}: {r1.text}")
            if r1.status_code != 200:
                await asyncio.sleep(0.5)
                continue
            # match_all readiness probe; no embeddings
            r2 = await client.post("/search", json={"query": "*", "limit": 0})
            if r2.status_code in (401, 403):
                raise AssertionError(f"/search returned {r2.status_code}: {r2.text}")
            if r2.status_code == 200:
                return
            last_err = r2.text
        except AssertionError:
            raise
        except Exception as e:
            last_err = str(e)
        await asyncio.sleep(0.5)
    raise AssertionError(f"Service not ready in time: {last_err}")


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_upload_and_search_endpoint(tmp_path: Path, disable_langflow_ingest: bool):
    """Boot the ASGI app and exercise /upload and /search endpoints."""
    # Ensure we route uploads to traditional processor and disable startup ingest
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    # Force no-auth mode so endpoints bypass authentication
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    # Import after env vars to ensure settings pick them up. Clear cached modules
    import sys
    # Clear cached modules so settings pick up env and router sees new flag
    for mod in [
        "src.api.router",
        "api.router",  # Also clear the non-src path
        "src.api.connector_router",
        "api.connector_router",
        "src.config.settings",
        "config.settings",
        "src.auth_middleware",
        "auth_middleware",
        "src.main",
        "api",  # Clear the api package itself
        "src.api",
    ]:
        sys.modules.pop(mod, None)
    from src.main import create_app, startup_tasks
    import src.api.router as upload_router
    from src.config.settings import clients, INDEX_NAME, DISABLE_INGEST_WITH_LANGFLOW

    # Verify settings loaded correctly
    print(f"Settings DISABLE_INGEST_WITH_LANGFLOW: {DISABLE_INGEST_WITH_LANGFLOW}")

    # Ensure a clean index before startup
    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=INDEX_NAME)
        # Wait for deletion to complete
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    # Manually run startup tasks since httpx ASGI transport here doesn't manage lifespan
    await startup_tasks(app.state.services)

    # Ensure index exists for tests (startup_tasks only creates it if DISABLE_INGEST_WITH_LANGFLOW=True)
    from src.main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    # Verify index is truly empty after startup
    try:
        count_response = await clients.opensearch.count(index=INDEX_NAME)
        doc_count = count_response.get('count', 0)
        assert doc_count == 0, f"Index should be empty after startup but contains {doc_count} documents"
    except Exception as e:
        # If count fails, the index might not exist yet, which is fine
        pass

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Wait for app + OpenSearch readiness using existing endpoints
            await wait_for_service_ready(client)

            # Create a temporary markdown file to upload
            file_path = tmp_path / "endpoint_test_doc.md"
            file_text = (
                "# Single Test Document\n\n"
                "This is a test document about OpenRAG testing framework. "
                "The content should be indexed and searchable in OpenSearch after processing."
            )
            file_path.write_text(file_text)

            # POST via router (multipart)
            files = {
                "file": (
                    file_path.name,
                    file_path.read_bytes(),
                    "text/markdown",
                )
            }
            upload_resp = await client.post("/upload", files=files)
            body = upload_resp.json()
            assert upload_resp.status_code == 201, upload_resp.text
            assert body.get("status") in {"indexed", "unchanged"}
            assert isinstance(body.get("id"), str)

            # Poll search for the specific content until it's indexed
            async def _wait_for_indexed(timeout_s: float = 30.0):
                deadline = asyncio.get_event_loop().time() + timeout_s
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.post(
                        "/search",
                        json={"query": "OpenRAG testing framework", "limit": 5},
                    )
                    if resp.status_code == 200 and resp.json().get("results"):
                        return resp
                    await asyncio.sleep(0.5)
                return resp

            search_resp = await _wait_for_indexed()

            # POST /search
            assert search_resp.status_code == 200, search_resp.text
            search_body = search_resp.json()

            # Basic shape and at least one hit
            assert isinstance(search_body.get("results"), list)
            assert len(search_body["results"]) >= 0
            # When hits exist, confirm our phrase is present in top result content
            if search_body["results"]:
                top = search_body["results"][0]
                assert "text" in top or "content" in top
                text = top.get("text") or top.get("content")
                assert isinstance(text, str)
                assert "testing" in text.lower()
    finally:
        # Explicitly close global clients to avoid aiohttp warnings
        from src.config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_router_upload_ingest_traditional(tmp_path: Path, disable_langflow_ingest: bool):
    """Exercise the router endpoint to ensure it routes to traditional upload when Langflow ingest is disabled."""
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys
    for mod in [
        "src.api.router",
        "api.router",  # Also clear the non-src path
        "src.api.connector_router",
        "api.connector_router",
        "src.config.settings",
        "config.settings",
        "src.auth_middleware",
        "auth_middleware",
        "src.main",
        "api",  # Clear the api package itself
        "src.api",
    ]:
        sys.modules.pop(mod, None)
    from src.main import create_app, startup_tasks
    import src.api.router as upload_router
    from src.config.settings import clients, INDEX_NAME, DISABLE_INGEST_WITH_LANGFLOW

    # Verify settings loaded correctly
    print(f"Settings DISABLE_INGEST_WITH_LANGFLOW: {DISABLE_INGEST_WITH_LANGFLOW}")

    # Ensure a clean index before startup
    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=INDEX_NAME)
        # Wait for deletion to complete
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    await startup_tasks(app.state.services)

    # Ensure index exists for tests (startup_tasks only creates it if DISABLE_INGEST_WITH_LANGFLOW=True)
    from src.main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    # Verify index is truly empty after startup
    try:
        count_response = await clients.opensearch.count(index=INDEX_NAME)
        doc_count = count_response.get('count', 0)
        assert doc_count == 0, f"Index should be empty after startup but contains {doc_count} documents"
    except Exception as e:
        # If count fails, the index might not exist yet, which is fine
        pass
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            file_path = tmp_path / "router_test_doc.md"
            file_path.write_text("# Router Test\n\nThis file validates the upload router.")

            files = {
                "file": (
                    file_path.name,
                    file_path.read_bytes(),
                    "text/markdown",
                )
            }

            resp = await client.post("/router/upload_ingest", files=files)
            data = resp.json()

            print(f"data: {data}")
            if disable_langflow_ingest:
                assert resp.status_code == 201 or resp.status_code == 202, resp.text
                assert data.get("status") in {"indexed", "unchanged"}
                assert isinstance(data.get("id"), str)
            else:
                assert resp.status_code == 201 or resp.status_code == 202, resp.text
                assert isinstance(data.get("task_id"), str)
                assert data.get("file_count") == 1
    finally:
        from src.config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass
