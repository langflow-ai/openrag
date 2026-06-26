import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest


# Pop cached modules so they reload with modified env vars
def _purge_modules():
    import sys

    for mod in [
        "api.router",
        "api.connector_router",
        "config.settings",
        "auth_middleware",
        "main",
        "api",
        "services",
        "services.search_service",
        "services.default_docs_service",
        "services.startup_orchestrator",
        "app.routes.internal",
        "app.routes",
        "app.container",
        "app.factory",
        "app.lifespan",
        "dependencies",
        "utils.opensearch_init",
    ]:
        sys.modules.pop(mod, None)


async def wait_for_service_ready(client: httpx.AsyncClient, timeout_s: float = 30.0):
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


async def wait_for_task_completion(
    client: httpx.AsyncClient, task_id: str, timeout_s: float = 60.0
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/tasks/{task_id}")
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                status = (data.get("status") or "").lower()
                if status == "completed":
                    return data
                if status == "failed":
                    raise AssertionError(f"Task {task_id} failed: {data}")
                last_payload = data
        await asyncio.sleep(1.0)
    raise AssertionError(f"Task {task_id} did not complete in time. Last payload: {last_payload}")


@pytest.mark.asyncio
async def test_non_langflow_csv_ingestion_with_splitting(tmp_path: Path):
    """Validate standard CSV ingestion using standard non-Langflow processing pipeline.

    Simulates parsing of a CSV file yielding a large table chunk (exceeding standard 8,000 token limit),
    verifying it gets split correctly and indexed into OpenSearch.
    """
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["EMBEDDING_MODEL"] = "text-embedding-3-small"
    os.environ["EMBEDDING_PROVIDER"] = "openai"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    _purge_modules()

    from config.settings import clients, get_index_name
    from main import create_app, startup_tasks

    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=get_index_name())
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    await startup_tasks(app.state.services)

    from main import _ensure_opensearch_index

    await _ensure_opensearch_index()

    # Mock the DoclingService conversion result
    # We want a table chunk whose token count exceeds 8,000 tokens (so it gets split)
    # "testlargephrase " is 3 tokens in cl100k_base. Repeating it 4000 times gives ~12,000 tokens.
    large_table_text = "testlargephrase " * 4000

    mock_docling_result = {
        "origin": {
            "binary_hash": "sha-csv-integration-123",
            "filename": "correlation_report.csv",
            "mimetype": "text/csv",
        },
        "texts": [],
        "tables": [
            {
                "prov": [{"page_no": 1}],
                "data": {
                    "table_cells": [
                        {
                            "start_row_offset_idx": 0,
                            "start_col_offset_idx": 0,
                            "text": large_table_text,
                        }
                    ]
                },
            }
        ],
    }

    # Patch convert_file method on DoclingService class
    from services.docling_service import DoclingService

    with patch.object(DoclingService, "convert_file", AsyncMock(return_value=mock_docling_result)):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Create mock CSV
            csv_path = tmp_path / "correlation_report.csv"
            csv_path.write_text("header1,header2\nvalue1,value2")

            files = {
                "file": (
                    csv_path.name,
                    csv_path.read_bytes(),
                    "text/csv",
                )
            }

            resp = await client.post("/router/upload_ingest", files=files)
            assert resp.status_code == 202, resp.text

            data = resp.json()
            task_id = data.get("task_id")
            assert task_id is not None

            # Wait for processing to complete
            await wait_for_task_completion(client, task_id)

            # Wait for search indices to refresh
            await asyncio.sleep(1)

            # Retrieve results from OpenSearch using search endpoint
            search_resp = await client.post(
                "/search",
                json={"query": "testlargephrase", "limit": 10},
            )
            assert search_resp.status_code == 200, search_resp.text

            results = search_resp.json().get("results", [])
            assert len(results) > 0, "No search results returned from indexed chunks"

            # Check direct OpenSearch doc count for this document ID
            opensearch_resp = await clients.opensearch.search(
                index=get_index_name(),
                body={"query": {"term": {"document_id": "sha-csv-integration-123"}}},
            )
            hits = opensearch_resp.get("hits", {}).get("hits", [])

            # Since the text is ~12,000 tokens, and max_tokens=8000,
            # it should be split into 2 chunks, resulting in 2 documents in OpenSearch.
            assert len(hits) == 2, f"Expected 2 indexed chunks, but got {len(hits)}"
            for hit in hits:
                source = hit.get("_source", {})
                assert source.get("document_id") == "sha-csv-integration-123"
                assert source.get("filename") == "correlation_report.csv"
                assert source.get("mimetype") == "text/csv"
                assert "testlargephrase" in source.get("text", "")
