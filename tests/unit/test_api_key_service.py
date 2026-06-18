import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_api_key_hash_uses_keyed_digest(monkeypatch):
    from services.api_key_service import API_KEY_HASH_PREFIX, APIKeyService

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")

    service = APIKeyService()
    keyed_hash = service._hash_key("orag_test_key")

    assert keyed_hash.startswith(API_KEY_HASH_PREFIX)
    assert keyed_hash != service._legacy_hash_key("orag_test_key")


@pytest.mark.asyncio
async def test_create_key_stores_hmac_hash(monkeypatch):
    from services.api_key_service import API_KEY_HASH_PREFIX, APIKeyService

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")
    monkeypatch.setattr("secrets.token_urlsafe", lambda n: "deterministic-token")

    opensearch_client = AsyncMock()
    opensearch_client.index.return_value = {"result": "created"}
    monkeypatch.setattr("config.settings.clients.opensearch", opensearch_client)

    service = APIKeyService()
    result = await service.create_key(
        user_id="user-1",
        user_email="user@example.com",
        name="test key",
    )

    assert result["success"] is True
    stored_doc = opensearch_client.index.await_args.kwargs["body"]
    assert stored_doc["key_hash"].startswith(API_KEY_HASH_PREFIX)
    assert stored_doc["key_hash"] == service._hash_key(result["api_key"])
    assert stored_doc["key_hash"] != result["api_key"]


@pytest.mark.asyncio
async def test_validate_key_accepts_and_migrates_legacy_hash(monkeypatch):
    from services.api_key_service import APIKeyService

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")

    service = APIKeyService()
    api_key = "orag_legacy_key"
    legacy_hash = service._legacy_hash_key(api_key)
    keyed_hash = service._hash_key(api_key)

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "key_id": "key-1",
                        "key_hash": legacy_hash,
                        "user_id": "user-1",
                        "user_email": "user@example.com",
                        "name": "legacy key",
                    }
                }
            ]
        }
    }
    monkeypatch.setattr("config.settings.clients.opensearch", opensearch_client)

    user_info = await service.validate_key(api_key)

    assert user_info == {
        "key_id": "key-1",
        "user_id": "user-1",
        "user_email": "user@example.com",
        "name": "legacy key",
    }
    terms = opensearch_client.search.await_args.kwargs["body"]["query"]["bool"]["must"][0]["terms"][
        "key_hash"
    ]
    assert terms == [keyed_hash, legacy_hash]

    update_doc = opensearch_client.update.await_args.kwargs["body"]["doc"]
    assert update_doc["key_hash"] == keyed_hash
    assert "last_used_at" in update_doc


@pytest.mark.asyncio
async def test_list_keys_returns_only_non_revoked_api_keys(monkeypatch) -> None:
    from services.api_key_service import APIKeyService

    service = APIKeyService()

    opensearch_client = AsyncMock()
    opensearch_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "key_id": "key-1",
                        "key_prefix": "orag_aaaaaaaa",
                        "name": "active key",
                        "created_at": "2026-06-15T10:03:58.016280",
                        "last_used_at": None,
                        "revoked": False,
                    }
                },
            ]
        }
    }
    monkeypatch.setattr("config.settings.clients.opensearch", opensearch_client)

    result = await service.list_keys(user_id="user-1")

    assert result["success"] is True
    assert result["keys"] == [
        {
            "key_id": "key-1",
            "key_prefix": "orag_aaaaaaaa",
            "name": "active key",
            "created_at": "2026-06-15T10:03:58.016280",
            "last_used_at": None,
            "revoked": False,
        }
    ]

    query_must = opensearch_client.search.await_args.kwargs["body"]["query"]["bool"]["must"]
    assert {"term": {"user_id": "user-1"}} in query_must
    assert {"term": {"revoked": False}} in query_must
