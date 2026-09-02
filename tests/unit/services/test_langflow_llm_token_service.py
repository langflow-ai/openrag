"""Short-lived Langflow LLM hop tokens."""

from __future__ import annotations

import time

import jwt
import pytest

from services.document_index_writer import DocumentIndexContext
from services.langflow_ingest_token_service import LangflowIngestTokenService
from services.langflow_llm_token_service import (
    LANGFLOW_LLM_AUDIENCE,
    LangflowLlmTokenService,
    langflow_hop_audience,
)

SECRET = "llm-hop-test-secret-with-32-bytes!!"


def test_round_trip_identifies_the_user():
    service = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    token = service.create_token(user_id="alice", email="a@x", name="Alice")
    user = service.validate_token(token)
    assert user.user_id == "alice"
    assert user.email == "a@x"
    assert user.provider == "langflow_llm"
    assert langflow_hop_audience(token) == LANGFLOW_LLM_AUDIENCE


def test_expired_token_is_rejected():
    service = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    token = service.create_token(user_id="alice")
    payload = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        audience=LANGFLOW_LLM_AUDIENCE,
        options={"verify_exp": False},
    )
    payload["exp"] = int(time.time()) - 10
    expired = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid Langflow LLM proxy token"):
        service.validate_token(expired)


def test_ingest_token_is_not_an_llm_token():
    ingest = LangflowIngestTokenService(secret=SECRET, ttl_seconds=60)
    token = ingest.create_token(
        DocumentIndexContext(
            document_id="doc-1",
            filename="a.pdf",
            mimetype="application/pdf",
            embedding_model="text-embedding-3-small",
            owner="alice",
            ingest_run_id="run-1",
        )
    )
    llm = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    with pytest.raises(ValueError, match="Invalid Langflow LLM proxy token"):
        llm.validate_token(token)
    assert langflow_hop_audience(token) == "openrag-langflow-ingest"


def test_wrong_scope_is_rejected():
    service = LangflowLlmTokenService(secret=SECRET, ttl_seconds=60)
    now = int(time.time())
    token = jwt.encode(
        {
            "aud": LANGFLOW_LLM_AUDIENCE,
            "scope": "ingest:chunks",
            "sub": "alice",
            "user_id": "alice",
            "iat": now,
            "exp": now + 60,
        },
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(ValueError, match="invalid scope"):
        service.validate_token(token)


def test_orag_key_is_not_a_hop_token():
    assert langflow_hop_audience("orag_abc") is None
    assert langflow_hop_audience("") is None
