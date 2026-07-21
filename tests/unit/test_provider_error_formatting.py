"""Unit tests for provider error message formatting helpers."""

from __future__ import annotations

import json

import pytest

from api.provider_validation import (
    format_provider_error_message,
    is_provider_credential_error,
    looks_like_provider_error_content,
    sanitize_provider_error_content,
)


def test_parse_ibm_iam_error_message():
    raw = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc","url":"https://iam.cloud.ibm.com"}}'
    )
    assert format_provider_error_message(raw) == (
        "Failed to authenticate with IBM Watson: Provided API key could not be found."
    )


def test_sanitize_strips_unparseable_json_for_credential_errors():
    raw = 'Incorrect API key provided {"error": "truncated'
    cleaned = sanitize_provider_error_content(raw)
    assert "{" not in cleaned
    assert "Incorrect API key provided" in cleaned or "revoked" in cleaned.lower()


def test_is_provider_credential_error():
    assert is_provider_credential_error("Incorrect API key provided")
    assert is_provider_credential_error("Provided API key could not be found.")
    assert is_provider_credential_error(json.dumps({"errorMessage": "api key revoked"}))
    assert not is_provider_credential_error("Rate limit exceeded")


def test_looks_like_provider_error_content():
    assert looks_like_provider_error_content("Error: boom")
    assert looks_like_provider_error_content(
        'Failed to authenticate: {"errorMessage":"Provided API key could not be found."}'
    )
    assert not looks_like_provider_error_content("OpenRAG is an open-source package.")


@pytest.mark.asyncio
async def test_resolve_ingest_error_message_probes_credentials_on_disconnect(monkeypatch):
    async def fake_probe():
        return "Provided API key could not be found."

    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_probe,
    )

    from api.provider_validation import resolve_ingest_error_message

    assert (
        await resolve_ingest_error_message("Server disconnected without sending a response.")
        == "Provided API key could not be found."
    )


@pytest.mark.asyncio
async def test_resolve_ingest_error_message_keeps_disconnect_when_probe_clean(monkeypatch):
    async def fake_probe():
        return None

    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_probe,
    )

    from api.provider_validation import resolve_ingest_error_message

    raw = "Server disconnected without sending a response."
    assert await resolve_ingest_error_message(raw) == raw


@pytest.mark.asyncio
async def test_probe_checks_non_selected_providers_with_keys(monkeypatch):
    """Revoked watsonx must be detected even when openai is the selected provider."""

    class FakeProvider:
        def __init__(self, api_key="", endpoint=None, project_id=None):
            self.api_key = api_key
            self.endpoint = endpoint
            self.project_id = project_id

    class FakeConfig:
        class knowledge:
            embedding_provider = "openai"
            embedding_model = "text-embedding-3-small"

        class agent:
            llm_provider = "openai"
            llm_model = "gpt-4o-mini"

        class providers:
            openai = FakeProvider(api_key="sk-ok")
            anthropic = FakeProvider()
            watsonx = FakeProvider(api_key="bad-watsonx", project_id="proj")
            ollama = FakeProvider()

        def get_embedding_provider_config(self):
            return self.providers.openai

        def get_llm_provider_config(self):
            return self.providers.openai

    async def fake_validate(**kwargs):
        if kwargs.get("provider") == "watsonx":
            raise Exception(
                "Failed to authenticate with IBM Watson: Provided API key could not be found."
            )

    monkeypatch.setattr("config.settings.get_openrag_config", lambda: FakeConfig())
    monkeypatch.setattr("api.provider_validation.validate_provider_setup", fake_validate)

    from api.provider_validation import probe_provider_credential_error

    assert (
        await probe_provider_credential_error()
        == "Failed to authenticate with IBM Watson: Provided API key could not be found."
    )
