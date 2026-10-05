"""`get_llm_proxy_user` records which kind of Langflow run minted a hop token.

The embeddings route reads it to give chat (query) embeddings their own lane
beside bulk ingestion at a concurrency-limited provider.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import dependencies
from services.langflow_llm_token_service import HOP_PURPOSE_CHAT, LangflowLlmTokenService

SECRET = "llm-hop-test-secret-with-32-bytes!!"


def _request(token: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": f"Bearer {token}"}, state=SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", [HOP_PURPOSE_CHAT, None])
async def test_a_hop_token_records_its_purpose(purpose):
    service = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    request = _request(service.create_token(user_id="alice", purpose=purpose))

    user = await dependencies.get_llm_proxy_user(
        request, token_service=service, api_key_service=None, session_manager=None
    )

    assert user.user_id == "alice"
    assert user.provider == "langflow_llm"
    assert request.state.user is user
    assert request.state.llm_hop_purpose == purpose


@pytest.mark.asyncio
async def test_a_non_hop_token_records_no_purpose(monkeypatch):
    service = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    api_user = SimpleNamespace(user_id="bob")
    fallback = AsyncMock(return_value=api_user)
    monkeypatch.setattr(dependencies, "resolve_api_key_user", fallback)
    request = _request("not-a-hop-token")

    user = await dependencies.get_llm_proxy_user(
        request, token_service=service, api_key_service=None, session_manager=None
    )

    assert user is api_user
    assert not hasattr(request.state, "llm_hop_purpose")
