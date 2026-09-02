"""Unit tests for provider error message formatting helpers."""

from __future__ import annotations

import json

import pytest

from api.provider_validation import (
    format_provider_error_message,
    is_generic_upstream_error,
    is_provider_credential_error,
    looks_like_provider_error_content,
    resolve_chat_stream_error_message,
    sanitize_provider_error_content,
)


def test_parse_ibm_iam_error_message():
    raw = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc","url":"https://iam.cloud.ibm.com"}}'
    )
    assert format_provider_error_message(raw) == "Provided API key is Invalid."


def test_format_dedupes_identical_auth_failures_with_different_request_ids():
    first = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"req-1"}}'
    )
    second = (
        'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E",'
        '"errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"req-2"}}'
    )
    assert format_provider_error_message(first) == format_provider_error_message(second)


def test_format_extracts_json_with_trailing_text():
    raw = (
        "Failed to initialize IBM WatsonX embedding model: Attempt of authenticating "
        "connection to service failed, please validate your credentials. Error: "
        '{"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found.",'
        '"context":{"requestId":"abc"}} '
        "IBM WatsonX requires additional configuration parameters. "
        "An error occurred while generating a response."
    )
    assert format_provider_error_message(raw) == "Provided API key is Invalid."
    assert "{" not in sanitize_provider_error_content(raw)


def test_is_provider_credential_error():
    assert is_provider_credential_error("Incorrect API key provided")
    assert is_provider_credential_error("Provided API key could not be found.")
    assert is_provider_credential_error("Provided API key is disabled.")
    assert is_provider_credential_error(json.dumps({"errorMessage": "api key revoked"}))
    assert not is_provider_credential_error("Rate limit exceeded")


def test_disabled_watsonx_key_embedding_dump_is_credential_error():
    """Langflow embedding failures for disabled keys omit 'failed to authenticate'."""
    raw = (
        "Error running graph: Error building Component Embedding Model: "
        "Failed to initialize IBM WatsonX embedding model: Attempt of authenticating "
        "connection to service failed, please validate your credentials. Error: "
        '{"errorCode":"BXNIM0420E","errorMessage":"Provided API key is disabled."}'
    )
    cleaned = sanitize_provider_error_content(raw)
    assert is_provider_credential_error(raw) or is_provider_credential_error(cleaned)
    assert cleaned == "Provided API key is disabled."
    assert "{" not in cleaned


def test_strip_error_label_prefixes_without_json():
    assert (
        format_provider_error_message(
            "Error running graph: Error building Component Language Model: Rate limit exceeded"
        )
        == "Rate limit exceeded"
    )
    # Bare "Error: …" is preserved (no label after Error).
    assert format_provider_error_message("Error: boom") == "Error: boom"


def test_looks_like_provider_error_content():
    assert looks_like_provider_error_content("Error: boom")
    assert looks_like_provider_error_content("An unknown error occurred.")
    assert looks_like_provider_error_content(
        'Failed to authenticate: {"errorMessage":"Provided API key could not be found."}'
    )
    assert not looks_like_provider_error_content("OpenRAG is an open-source package.")
    assert is_generic_upstream_error("An unknown error occurred.")


def test_resolve_chat_stream_error_message_keeps_generic_without_probing():
    # Sync helper must not probe — that stays in the async path.
    assert (
        resolve_chat_stream_error_message("An unknown error occurred.")
        == "An unknown error occurred."
    )


@pytest.mark.asyncio
async def test_resolve_chat_stream_error_message_async_probes_llm_on_generic(monkeypatch):
    async def fake_llm_probe():
        return (
            "Model 'ibm/granite-4-h-small' was not found. "
            "This model may be unsupported, deprecated, or removed."
        )

    async def fake_cred_probe():
        raise AssertionError("must prefer LLM probe over credential probe")

    monkeypatch.setattr(
        "api.provider_validation.probe_chat_llm_error",
        fake_llm_probe,
    )
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_cred_probe,
    )

    from api.provider_validation import resolve_chat_stream_error_message_async

    assert "granite-4-h-small" in await resolve_chat_stream_error_message_async(
        "An unknown error occurred."
    )


@pytest.mark.asyncio
async def test_resolve_chat_stream_error_message_async_falls_back_to_credentials(
    monkeypatch,
):
    async def fake_llm_probe():
        return None

    async def fake_cred_probe():
        return "Provided API key is disabled."

    monkeypatch.setattr(
        "api.provider_validation.probe_chat_llm_error",
        fake_llm_probe,
    )
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_cred_probe,
    )

    from api.provider_validation import resolve_chat_stream_error_message_async

    assert (
        await resolve_chat_stream_error_message_async("An unknown error occurred.")
        == "Provided API key is disabled."
    )


@pytest.mark.asyncio
async def test_resolve_chat_stream_error_message_async_keeps_specific_errors(monkeypatch):
    async def fake_probe():
        raise AssertionError("must not probe specific errors")

    monkeypatch.setattr(
        "api.provider_validation.probe_chat_llm_error",
        fake_probe,
    )
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_probe,
    )

    from api.provider_validation import resolve_chat_stream_error_message_async

    assert (
        await resolve_chat_stream_error_message_async("Rate limit exceeded")
        == "Rate limit exceeded"
    )


@pytest.mark.asyncio
async def test_probe_chat_llm_error_surfaces_missing_model(monkeypatch):
    class FakeProvider:
        def __init__(self):
            self.api_key = "wx-ok"
            self.endpoint = "https://us-south.ml.cloud.ibm.com"
            self.project_id = "proj"

    class FakeConfig:
        class agent:
            llm_provider = "watsonx"
            llm_model = "ibm/granite-4-h-small"

        def get_llm_provider_config(self):
            return FakeProvider()

    async def fake_validate(**kwargs):
        assert kwargs.get("test_completion") is True
        assert kwargs.get("llm_model") == "ibm/granite-4-h-small"
        assert kwargs.get("embedding_model") is None
        raise Exception(
            "Model 'ibm/granite-4-h-small' was not found. "
            "This model may be unsupported, deprecated, or removed."
        )

    monkeypatch.setattr("config.settings.get_openrag_config", lambda: FakeConfig())
    monkeypatch.setattr("api.provider_validation.validate_provider_setup", fake_validate)

    from api.provider_validation import probe_chat_llm_error

    result = await probe_chat_llm_error()
    assert result is not None
    assert "granite-4-h-small" in result
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_resolve_ingest_error_message_probes_generic_embedding_with_credentials(
    monkeypatch,
):
    """Opaque Langflow failures must expose missing Azure deployments.

    Generic LiteLLM providers store their connection fields in ``credentials``
    rather than legacy ``api_key`` / ``endpoint`` attributes.
    """

    credentials = {
        "api_key": "azure-key",
        "api_base": "https://example.openai.azure.com",
        "api_version": "2025-01-01-preview",
    }

    class GenericProvider:
        configured = True

    class FakeProviders:
        custom = {"azure": GenericProvider()}
        openai = None
        anthropic = None
        watsonx = None
        ollama = None

        def credential_values(self, provider):
            assert provider == "azure"
            return dict(credentials)

    class FakeConfig:
        class knowledge:
            embedding_provider = "azure"
            embedding_model = "missing-embedding-deployment"

        class agent:
            llm_provider = "azure"
            llm_model = "missing-chat-deployment"

        providers = FakeProviders()

        def get_embedding_provider_config(self):
            return self.providers.custom["azure"]

        def get_llm_provider_config(self):
            return self.providers.custom["azure"]

    calls = []

    async def fake_validate(**kwargs):
        calls.append(kwargs)
        assert kwargs["embedding_model"] == "missing-embedding-deployment"
        assert kwargs["credentials"] == credentials
        raise Exception("The API deployment for this resource does not exist.")

    monkeypatch.setattr("config.settings.get_openrag_config", lambda: FakeConfig())
    monkeypatch.setattr("api.provider_validation.validate_provider_setup", fake_validate)

    from api.provider_validation import resolve_ingest_error_message

    result = await resolve_ingest_error_message("Server disconnected without sending a response.")

    assert result == "The API deployment for this resource does not exist."
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_probe_chat_llm_error_uses_generic_provider_credentials(monkeypatch):
    credentials = {
        "api_key": "azure-key",
        "api_base": "https://example.openai.azure.com",
        "api_version": "2025-01-01-preview",
    }

    class GenericProvider:
        configured = True

    class FakeProviders:
        custom = {"azure": GenericProvider()}

        def credential_values(self, provider):
            assert provider == "azure"
            return dict(credentials)

    class FakeConfig:
        class agent:
            llm_provider = "azure"
            llm_model = "missing-chat-deployment"

        providers = FakeProviders()

        def get_llm_provider_config(self):
            return self.providers.custom["azure"]

    async def fake_validate(**kwargs):
        assert kwargs["llm_model"] == "missing-chat-deployment"
        assert kwargs["credentials"] == credentials
        raise Exception("DeploymentNotFound: missing-chat-deployment")

    monkeypatch.setattr("config.settings.get_openrag_config", lambda: FakeConfig())
    monkeypatch.setattr("api.provider_validation.validate_provider_setup", fake_validate)

    from api.provider_validation import probe_chat_llm_error

    assert await probe_chat_llm_error() == "DeploymentNotFound: missing-chat-deployment"


@pytest.mark.asyncio
async def test_resolve_ingest_error_message_probes_credentials_on_disconnect(monkeypatch):
    async def fake_none():
        return None

    async def fake_cred_probe():
        return "Provided API key could not be found."

    monkeypatch.setattr("api.provider_validation.probe_embedding_error", fake_none)
    monkeypatch.setattr("api.provider_validation.probe_chat_llm_error", fake_none)
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_cred_probe,
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

    monkeypatch.setattr("api.provider_validation.probe_embedding_error", fake_probe)
    monkeypatch.setattr("api.provider_validation.probe_chat_llm_error", fake_probe)
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_probe,
    )

    from api.provider_validation import resolve_ingest_error_message

    raw = "Server disconnected without sending a response."
    assert await resolve_ingest_error_message(raw) == raw


@pytest.mark.asyncio
async def test_resolve_ingest_error_message_prefers_model_over_mislabeled_api_key(
    monkeypatch,
):
    """Langflow often says API key invalid when the chat/LLM model is missing."""

    async def fake_none():
        return None

    async def fake_llm_probe():
        return (
            "Model 'ibm/granite-4-h-small' was not found. "
            "This model may be unsupported, deprecated, or removed."
        )

    async def fake_cred_probe():
        raise AssertionError("credential probe must not run after LLM model diagnosis")

    monkeypatch.setattr("api.provider_validation.probe_embedding_error", fake_none)
    monkeypatch.setattr("api.provider_validation.probe_chat_llm_error", fake_llm_probe)
    monkeypatch.setattr(
        "api.provider_validation.probe_provider_credential_error",
        fake_cred_probe,
    )

    from api.provider_validation import resolve_ingest_error_message

    result = await resolve_ingest_error_message("API key is invalid")
    assert "granite-4-h-small" in result
    assert "not found" in result.lower()


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
            raise Exception("Provided API key could not be found.")

    monkeypatch.setattr("config.settings.get_openrag_config", lambda: FakeConfig())
    monkeypatch.setattr("api.provider_validation.validate_provider_setup", fake_validate)

    from api.provider_validation import probe_provider_credential_error

    assert await probe_provider_credential_error() == "Provided API key is Invalid."
