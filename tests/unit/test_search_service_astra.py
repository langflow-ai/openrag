from unittest.mock import AsyncMock, Mock

import auth_context
import pytest

import services.search_service as search_service_module
from services.search_service import SearchService
from session_manager import User


@pytest.mark.asyncio
async def test_search_service_routes_queries_through_backend(monkeypatch):
    backend = Mock()
    backend.search = AsyncMock(return_value={"results": [], "aggregations": {}, "total": 0})
    session_manager = Mock()
    session_manager.get_user.return_value = User(
        user_id="u1",
        email="u1@example.com",
        name="User One",
    )

    monkeypatch.setattr(
        search_service_module,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )
    monkeypatch.setattr(
        search_service_module,
        "get_auth_context",
        lambda: ("u1", "Bearer test-token"),
    )
    monkeypatch.setattr(auth_context, "get_search_filters", lambda: {"data_sources": ["animals.md"]})
    monkeypatch.setattr(auth_context, "get_search_limit", lambda: 7)
    monkeypatch.setattr(auth_context, "get_score_threshold", lambda: 0.42)

    service = SearchService(session_manager=session_manager)
    service._generate_query_embedding = AsyncMock(return_value=[0.1, 0.2, 0.3])

    result = await service.search_tool(
        "purple elephants",
        embedding_model="text-embedding-3-small",
    )

    assert result == {"results": [], "aggregations": {}, "total": 0}
    backend.search.assert_awaited_once()
    _, kwargs = backend.search.await_args
    assert kwargs["query"] == "purple elephants"
    assert kwargs["embedding_model"] == "text-embedding-3-small"
    assert kwargs["filters"] == {"data_sources": ["animals.md"]}
    assert kwargs["limit"] == 7
    assert kwargs["score_threshold"] == 0.42
    assert kwargs["access_context"].user_id == "u1"
    assert kwargs["access_context"].user_email == "u1@example.com"


@pytest.mark.asyncio
async def test_search_service_search_passes_explicit_user_context(monkeypatch):
    backend = Mock()
    backend.search = AsyncMock(return_value={"results": [], "aggregations": {}, "total": 0})

    monkeypatch.setattr(
        search_service_module,
        "get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    service = SearchService(session_manager=Mock())
    service._generate_query_embedding = AsyncMock()

    await service.search(
        "purple elephants",
        user_id="u1",
        user_email="u1@example.com",
        jwt_token="Bearer test-token",
        filters={},
        limit=10,
        score_threshold=0.0,
    )

    _, kwargs = backend.search.await_args
    assert kwargs["access_context"].user_id == "u1"
    assert kwargs["access_context"].user_email == "u1@example.com"
