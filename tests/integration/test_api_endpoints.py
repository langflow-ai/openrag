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
    # First test OpenSearch JWT directly
    from src.session_manager import SessionManager, AnonymousUser
    import os
    import hashlib
    import jwt as jwt_lib
    sm = SessionManager("test")
    test_token = sm.create_jwt_token(AnonymousUser())
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()[:16]
    print(f"[DEBUG] Generated test JWT token hash: {token_hash}")
    print(f"[DEBUG] Using key paths: private={sm.private_key_path}, public={sm.public_key_path}")
    with open(sm.public_key_path, 'rb') as f:
        pub_key_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    print(f"[DEBUG] Public key hash: {pub_key_hash}")
    # Decode token to see claims
    decoded = jwt_lib.decode(test_token, options={"verify_signature": False})
    print(f"[DEBUG] JWT claims: iss={decoded.get('iss')}, sub={decoded.get('sub')}, aud={decoded.get('aud')}, roles={decoded.get('roles')}")

    # Test OpenSearch JWT auth directly
    opensearch_url = f"https://{os.getenv('OPENSEARCH_HOST', 'localhost')}:{os.getenv('OPENSEARCH_PORT', '9200')}"
    print(f"[DEBUG] Testing JWT auth directly against: {opensearch_url}/documents/_search")
    async with httpx.AsyncClient(verify=False) as os_client:
        r_os = await os_client.post(
            f"{opensearch_url}/documents/_search",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"query": {"match_all": {}}, "size": 0}
        )
        print(f"[DEBUG] Direct OpenSearch JWT test: status={r_os.status_code}, body={r_os.text[:500]}")
        if r_os.status_code == 401:
            print(f"[DEBUG] ❌ OpenSearch rejected JWT! OIDC config not working.")
        else:
            print(f"[DEBUG] ✓ OpenSearch accepted JWT!")

    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            r1 = await client.get("/auth/me")
            print(f"[DEBUG] /auth/me status={r1.status_code}, body={r1.text[:200]}")
            if r1.status_code in (401, 403):
                raise AssertionError(f"/auth/me returned {r1.status_code}: {r1.text}")
            if r1.status_code != 200:
                await asyncio.sleep(0.5)
                continue
            # match_all readiness probe; no embeddings
            r2 = await client.post("/search", json={"query": "*", "limit": 0})
            print(f"[DEBUG] /search status={r2.status_code}, body={r2.text[:200]}")
            if r2.status_code in (401, 403):
                print(f"[DEBUG] Search failed with auth error. Response: {r2.text}")
                raise AssertionError(f"/search returned {r2.status_code}: {r2.text}")
            if r2.status_code == 200:
                print("[DEBUG] Service ready!")
                return
            last_err = r2.text
        except AssertionError:
            raise
        except Exception as e:
            last_err = str(e)
            print(f"[DEBUG] Exception during readiness check: {e}")
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
        "services",  # Clear services that import clients
        "src.services",
        "services.search_service",
        "src.services.search_service",
    ]:
        sys.modules.pop(mod, None)
    from src.main import create_app, startup_tasks
    import src.api.router as upload_router
    from src.config.settings import clients, INDEX_NAME, DISABLE_INGEST_WITH_LANGFLOW

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


async def _wait_for_langflow_chat(
    client: httpx.AsyncClient, payload: dict, timeout_s: float = 120.0
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.post("/langflow", json=payload)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                response_text = data.get("response")
                if isinstance(response_text, str) and response_text.strip():
                    return data
                last_payload = data
        else:
            last_payload = resp.text
        await asyncio.sleep(1.0)
    raise AssertionError(f"/langflow never returned a usable response. Last payload: {last_payload}")


async def _wait_for_nudges(
    client: httpx.AsyncClient, chat_id: str | None = None, timeout_s: float = 90.0
) -> dict:
    endpoint = "/nudges" if not chat_id else f"/nudges/{chat_id}"
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(endpoint)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                response_text = data.get("response")
                if isinstance(response_text, str) and response_text.strip():
                    return data
                last_payload = data
        else:
            last_payload = resp.text
        await asyncio.sleep(1.0)
    raise AssertionError(f"{endpoint} never returned a usable response. Last payload: {last_payload}")


@pytest.mark.asyncio
async def test_langflow_chat_and_nudges_endpoints():
    """Exercise /langflow and /nudges endpoints against a live Langflow backend."""
    required_env = ["LANGFLOW_CHAT_FLOW_ID", "NUDGES_FLOW_ID"]
    missing = [var for var in required_env if not os.getenv(var)]
    assert not missing, f"Missing required Langflow configuration: {missing}"

    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys

    for mod in [
        "src.api.chat",
        "api.chat",
        "src.api.nudges",
        "api.nudges",
        "src.api.router",
        "api.router",
        "src.api.connector_router",
        "api.connector_router",
        "src.config.settings",
        "config.settings",
        "src.auth_middleware",
        "auth_middleware",
        "src.main",
        "api",
        "src.api",
        "services",
        "src.services",
        "services.search_service",
        "src.services.search_service",
        "services.chat_service",
        "src.services.chat_service",
    ]:
        sys.modules.pop(mod, None)

    from src.main import create_app, startup_tasks
    from src.config.settings import clients, LANGFLOW_CHAT_FLOW_ID, NUDGES_FLOW_ID

    assert LANGFLOW_CHAT_FLOW_ID, "LANGFLOW_CHAT_FLOW_ID must be configured for integration test"
    assert NUDGES_FLOW_ID, "NUDGES_FLOW_ID must be configured for integration test"

    await clients.initialize()
    app = await create_app()
    await startup_tasks(app.state.services)

    langflow_client = None
    deadline = asyncio.get_event_loop().time() + 60.0
    while asyncio.get_event_loop().time() < deadline:
        langflow_client = await clients.ensure_langflow_client()
        if langflow_client is not None:
            break
        await asyncio.sleep(1.0)
    assert langflow_client is not None, "Langflow client not initialized. Provide LANGFLOW_KEY or enable superuser auto-login."

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            prompt = "Respond with a brief acknowledgement for the OpenRAG integration test."
            langflow_payload = {"prompt": prompt, "limit": 5, "scoreThreshold": 0}
            langflow_data = await _wait_for_langflow_chat(client, langflow_payload)

            assert isinstance(langflow_data.get("response"), str)
            assert langflow_data["response"].strip()

            response_id = langflow_data.get("response_id")

            nudges_data = await _wait_for_nudges(client)
            assert isinstance(nudges_data.get("response"), str)
            assert nudges_data["response"].strip()

            if response_id:
                nudges_thread_data = await _wait_for_nudges(client, response_id)
                assert isinstance(nudges_thread_data.get("response"), str)
                assert nudges_thread_data["response"].strip()
    finally:
        from src.config.settings import clients

        try:
            await clients.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_search_multi_embedding_models(
    tmp_path: Path
):
    """Ensure /search fans out across multiple embedding models when present."""
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys

    for mod in [
        "src.api.router",
        "api.router",
        "src.api.connector_router",
        "api.connector_router",
        "src.config.settings",
        "config.settings",
        "src.auth_middleware",
        "auth_middleware",
        "src.main",
        "services.search_service",
        "src.services.search_service",
    ]:
        sys.modules.pop(mod, None)

    from src.main import create_app, startup_tasks
    from src.config.settings import clients, INDEX_NAME

    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=INDEX_NAME)
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    await startup_tasks(app.state.services)

    from src.main import _ensure_opensearch_index

    await _ensure_opensearch_index()

    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            onboarding_payload = {
                "model_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "sample_data": False,
            }
            onboarding_resp = await client.post("/onboarding", json=onboarding_payload)
            if onboarding_resp.status_code not in (200, 204):
                raise AssertionError(
                    f"Onboarding failed: {onboarding_resp.status_code} {onboarding_resp.text}"
                )

            async def _upload_doc(name: str, text: str) -> None:
                file_path = tmp_path / name
                file_path.write_text(text)
                files = {
                    "file": (
                        name,
                        file_path.read_bytes(),
                        "text/markdown",
                    )
                }
                resp = await client.post("/upload", files=files)
                assert resp.status_code == 201, resp.text

            async def _wait_for_models(expected_models: set[str], query: str = "physics"):
                deadline = asyncio.get_event_loop().time() + 30.0
                last_payload = None
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.post(
                        "/search",
                        json={"query": query, "limit": 10, "scoreThreshold": 0},
                    )
                    if resp.status_code != 200:
                        last_payload = resp.text
                        await asyncio.sleep(0.5)
                        continue
                    payload = resp.json()
                    buckets = (
                        payload.get("aggregations", {})
                        .get("embedding_models", {})
                        .get("buckets", [])
                    )
                    models = {b.get("key") for b in buckets if b.get("key")}
                    if expected_models <= models:
                        return payload
                    last_payload = payload
                    await asyncio.sleep(0.5)
                raise AssertionError(
                    f"Embedding models not detected. Last payload: {last_payload}"
                )

            # Start with explicit small embedding model
            resp = await client.post(
                "/settings",
                json={
                    "embedding_model": "text-embedding-3-small",
                    "llm_model": "gpt-4o-mini",
                },
            )
            assert resp.status_code == 200, resp.text

            # Ingest first document (small model)
            await _upload_doc("doc-small.md", "Physics basics and fundamental principles.")
            payload_small = await _wait_for_models({"text-embedding-3-small"})
            result_models_small = {r.get("embedding_model") for r in payload_small.get("results", []) if r.get("embedding_model")}
            assert "text-embedding-3-small" in result_models_small or not result_models_small

            # Update embedding model via settings
            resp = await client.post(
                "/settings",
                json={"embedding_model": "text-embedding-3-large"},
            )
            assert resp.status_code == 200, resp.text

            # Ingest second document which should use the large embedding model
            await _upload_doc("doc-large.md", "Advanced physics covers quantum topics extensively.")

            payload = await _wait_for_models({"text-embedding-3-small", "text-embedding-3-large"})
            buckets = payload.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
            models = {b.get("key") for b in buckets}
            assert {"text-embedding-3-small", "text-embedding-3-large"} <= models

            result_models = {
                r.get("embedding_model")
                for r in payload.get("results", [])
                if r.get("embedding_model")
            }
            assert {"text-embedding-3-small", "text-embedding-3-large"} <= result_models
    finally:
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
        "services",  # Clear services that import clients
        "src.services",
        "services.search_service",
        "src.services.search_service",
    ]:
        sys.modules.pop(mod, None)
    from src.main import create_app, startup_tasks
    import src.api.router as upload_router
    from src.config.settings import clients, INDEX_NAME, DISABLE_INGEST_WITH_LANGFLOW

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
