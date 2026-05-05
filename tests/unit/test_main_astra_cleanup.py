from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_delete_existing_default_docs_uses_backend_filters(monkeypatch):
    import main

    backend = Mock()
    backend.delete_by_filter_sets = AsyncMock(return_value=5)
    session_manager = Mock()
    session_manager.get_effective_jwt_token.return_value = "Bearer anon-token"

    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )

    await main._delete_existing_default_docs(session_manager, "openrag_docs")

    backend.delete_by_filter_sets.assert_awaited_once()
    args, kwargs = backend.delete_by_filter_sets.await_args
    assert args[0] == [
        {
            "connector_type": "openrag_docs",
            "owner_email": "anonymous@localhost",
        },
        {
            "connector_type": "local",
            "is_sample_data": "true",
        },
    ]
    assert kwargs["match_any"] is True
    assert kwargs["access_context"].user_id == "anonymous"
