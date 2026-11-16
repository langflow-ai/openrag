import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from services.api_key_service import APIKeyService

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    yield factory

    await engine.dispose()


def test_api_key_hash_uses_keyed_digest(monkeypatch):
    from services.api_key_service import API_KEY_HASH_PREFIX

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")

    service = APIKeyService()
    keyed_hash = service._hash_key("orag_test_key")

    assert keyed_hash.startswith(API_KEY_HASH_PREFIX)
    assert keyed_hash != service._legacy_hash_key("orag_test_key")


@pytest.mark.asyncio
async def test_create_then_validate_roundtrip_stamps_last_used(session_factory, monkeypatch):
    """Primary path: a created key validates, resolves its owner's email via
    the users join, and gets last_used_at stamped."""
    from db.models import User
    from db.repositories import ApiKeyRepo
    from db.repositories._helpers import email_lookup_hash

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")
    service = APIKeyService(session_factory=session_factory)

    async with session_factory() as session:
        session.add(
            User(
                id="user-1",
                oauth_provider="google",
                oauth_subject="user-1",
                email="user@example.com",
                email_lookup_hash=email_lookup_hash("user@example.com"),
            )
        )
        await session.commit()

    created = await service.create_key(user_id="user-1", name="my key")
    info = await service.validate_key(created["api_key"])

    assert info == {
        "key_id": created["key_id"],
        "user_id": "user-1",
        "user_email": "user@example.com",
        "name": "my key",
    }
    # mark_used ran (parity with the OpenSearch last_used_at update)
    async with session_factory() as session:
        row = await ApiKeyRepo(session).get_by_id(created["key_id"])

    assert row is not None
    assert row.last_used_at is not None


@pytest.mark.asyncio
async def test_create_key_stores_hmac_hash(session_factory, monkeypatch):
    from db.repositories import ApiKeyRepo
    from services.api_key_service import API_KEY_HASH_PREFIX

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")
    service = APIKeyService(session_factory=session_factory)
    result = await service.create_key(user_id="user-1", name="test key")

    assert result["success"] is True
    assert result["api_key"].startswith("orag_")

    async with session_factory() as session:
        row = await ApiKeyRepo(session).get_by_id(result["key_id"])

    assert row is not None
    assert row.key_hash.startswith(API_KEY_HASH_PREFIX)
    assert row.key_hash == service._hash_key(result["api_key"])
    assert row.key_hash != result["api_key"]


@pytest.mark.asyncio
async def test_validate_key_accepts_and_migrates_legacy_hash(session_factory, monkeypatch):
    from db.models import ApiKey, User
    from db.repositories._helpers import email_lookup_hash

    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")
    service = APIKeyService(session_factory=session_factory)
    api_key = "orag_legacy_key"

    async with session_factory() as session:
        session.add(
            User(
                id="user-1",
                oauth_provider="google",
                oauth_subject="user-1",
                email="user@example.com",
                email_lookup_hash=email_lookup_hash("user@example.com"),
            )
        )
        session.add(
            ApiKey(
                id="key-1",
                user_id="user-1",
                name="legacy key",
                key_hash=service._legacy_hash_key(api_key),
                key_prefix="orag_legacy1",
            )
        )
        await session.commit()

    user_info = await service.validate_key(api_key)
    assert user_info == {
        "key_id": "key-1",
        "user_id": "user-1",
        "user_email": "user@example.com",
        "name": "legacy key",
    }


@pytest.mark.asyncio
async def test_validate_key_opensearch_fallback_accepts_and_migrates_legacy_has(
    session_factory, monkeypatch
) -> None:
    monkeypatch.setattr("config.settings.SESSION_SECRET", "unit-test-session-secret")

    service = APIKeyService(session_factory=session_factory)
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
async def test_list_keys_returns_only_non_revoked_api_keys(session_factory, monkeypatch) -> None:
    from db.models import ApiKey

    service = APIKeyService(session_factory=session_factory)
    async with session_factory() as session:
        session.add(
            ApiKey(id="k1", user_id="user-1", name="active", key_hash="h1", key_prefix="orag_a")
        )
        session.add(
            ApiKey(
                id="k2",
                user_id="user-1",
                name="revoked",
                key_hash="h2",
                key_prefix="orag_b",
                revoked=True,
            )
        )
        await session.commit()

    result = await service.list_keys("user-1", oauth_subject="subject-1")
    assert [k["key_id"] for k in result["keys"]] == ["k1"]
    assert set(result["keys"][0]) == {
        "key_id",
        "key_prefix",
        "name",
        "created_at",
        "last_used_at",
        "revoked",
    }


@pytest.mark.asyncio
async def test_list_keys_opensearch_fallback_when_sqlite_empty(
    session_factory, monkeypatch
) -> None:
    service = APIKeyService(session_factory=session_factory)

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

    result = await service.list_keys(user_id="user-1", oauth_subject="oauth-subject-1")

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
    assert {"term": {"user_id": "oauth-subject-1"}} in query_must
    assert {"term": {"revoked": False}} in query_must


@pytest.mark.asyncio
async def test_list_keys_all_revoked_returns_empty_without_fallback(
    session_factory, monkeypatch
) -> None:
    from db.models import ApiKey

    service = APIKeyService(session_factory=session_factory)
    async with session_factory() as session:
        session.add(
            ApiKey(
                id="k1",
                user_id="user-1",
                name="revoked",
                key_hash="h1",
                key_prefix="orag_a",
                revoked=True,
            )
        )
        await session.commit()

    opensearch_client = AsyncMock()
    monkeypatch.setattr("config.settings.clients.opensearch", opensearch_client)

    result = await service.list_keys("user-1", oauth_subject="subject-1")
    assert result == {"success": True, "keys": []}
    opensearch_client.search.assert_not_awaited()
