import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.settings as settings_api
from fastapi import HTTPException
from session_manager import User


@pytest.mark.asyncio
async def test_refresh_openrag_docs_returns_refreshed_shape(monkeypatch):
    async def _fake_refresh_default_openrag_docs(**kwargs):
        return True

    import main

    monkeypatch.setattr(
        main,
        "refresh_default_openrag_docs",
        _fake_refresh_default_openrag_docs,
        raising=True,
    )

    result = await settings_api.refresh_openrag_docs(
        document_service=object(),
        task_service=object(),
        langflow_file_service=object(),
        session_manager=object(),
        user=User(user_id="u1", email="u1@example.com", name="User One"),
    )

    assert result.refreshed is True
    assert result.message == "OpenRAG docs were refreshed."


@pytest.mark.asyncio
async def test_refresh_openrag_docs_returns_skipped_shape(monkeypatch):
    async def _fake_refresh_default_openrag_docs(**kwargs):
        return False

    import main

    monkeypatch.setattr(
        main,
        "refresh_default_openrag_docs",
        _fake_refresh_default_openrag_docs,
        raising=True,
    )

    result = await settings_api.refresh_openrag_docs(
        document_service=object(),
        task_service=object(),
        langflow_file_service=object(),
        session_manager=object(),
        user=User(user_id="u2", email="u2@example.com", name="User Two"),
    )

    assert result.refreshed is False
    assert result.message == "OpenRAG docs refresh was skipped by current configuration."


@pytest.mark.asyncio
async def test_refresh_openrag_docs_wraps_exceptions(monkeypatch):
    async def _fake_refresh_default_openrag_docs(**kwargs):
        raise RuntimeError("boom")

    import main

    monkeypatch.setattr(
        main,
        "refresh_default_openrag_docs",
        _fake_refresh_default_openrag_docs,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await settings_api.refresh_openrag_docs(
            document_service=object(),
            task_service=object(),
            langflow_file_service=object(),
            session_manager=object(),
            user=User(user_id="u3", email="u3@example.com", name="User Three"),
        )

    assert exc_info.value.status_code == 500
    assert "Failed to refresh OpenRAG docs" in str(exc_info.value.detail)


def test_refresh_endpoint_requires_auth_in_auth_mode(monkeypatch):
    import config.settings as app_settings

    app = FastAPI()
    app.add_api_route(
        "/openrag-docs/refresh",
        settings_api.refresh_openrag_docs,
        methods=["POST"],
    )

    # Force auth mode for this test so get_current_user requires auth cookie.
    monkeypatch.setattr(app_settings, "is_no_auth_mode", lambda: False, raising=True)

    # Satisfy service dependencies for route construction/execution.
    app.dependency_overrides[settings_api.get_document_service] = lambda: object()
    app.dependency_overrides[settings_api.get_task_service] = lambda: object()
    app.dependency_overrides[settings_api.get_langflow_file_service] = lambda: object()
    app.dependency_overrides[settings_api.get_session_manager] = lambda: object()

    with TestClient(app) as client:
        resp = client.post("/openrag-docs/refresh")

    assert resp.status_code == 401
    body = resp.json()
    assert body.get("detail") == "Authentication required"


def test_refresh_endpoint_returns_expected_http_response_shape(monkeypatch):
    async def _fake_refresh_default_openrag_docs(**kwargs):
        return True

    import main

    monkeypatch.setattr(
        main,
        "refresh_default_openrag_docs",
        _fake_refresh_default_openrag_docs,
        raising=True,
    )

    app = FastAPI()
    app.add_api_route(
        "/openrag-docs/refresh",
        settings_api.refresh_openrag_docs,
        methods=["POST"],
    )

    # Route-level dependency overrides for successful request execution.
    app.dependency_overrides[settings_api.get_document_service] = lambda: object()
    app.dependency_overrides[settings_api.get_task_service] = lambda: object()
    app.dependency_overrides[settings_api.get_langflow_file_service] = lambda: object()
    app.dependency_overrides[settings_api.get_session_manager] = lambda: object()
    app.dependency_overrides[settings_api.get_current_user] = lambda: User(
        user_id="u4",
        email="u4@example.com",
        name="User Four",
    )

    with TestClient(app) as client:
        resp = client.post("/openrag-docs/refresh")

    assert resp.status_code == 200
    assert resp.json() == {
        "message": "OpenRAG docs were refreshed.",
        "refreshed": True,
    }
