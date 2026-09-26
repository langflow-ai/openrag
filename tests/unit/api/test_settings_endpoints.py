"""
Unit tests for api.settings.endpoints
Validates error handling in update_docling_preset endpoint.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.settings import DoclingPresetBody, update_docling_preset
from api.settings.models import (
    AssistantMessage,
    OnboardingBody,
    OnboardingFunctionCall,
    SettingsUpdateBody,
)
from session_manager import User


@pytest.mark.asyncio
async def test_update_docling_preset_invalid_preset_returns_400():
    """Test that an invalid preset value returns 400 status code.

    This test ensures that the HTTPException with status_code=400 raised
    for invalid presets is not masked by the broad Exception handler.
    Regression test for issue #1586.
    """
    # Create a body with an invalid preset
    body = DoclingPresetBody(preset="nonexistent_preset")

    # Mock dependencies
    session_manager = AsyncMock()
    user = MagicMock(spec=User)

    # Call the endpoint and expect HTTPException with 400
    with pytest.raises(HTTPException) as exc_info:
        await update_docling_preset(body=body, session_manager=session_manager, user=user)

    # Assert it's a 400 error (not 500)
    assert exc_info.value.status_code == 400
    assert "Invalid preset" in exc_info.value.detail
    assert "nonexistent_preset" in exc_info.value.detail


def test_assistant_message_citation_serialization():
    """Test AssistantMessage model citation parsing with text and metadata."""
    payload = {
        "role": "assistant",
        "content": "Here is the response [1]",
        "timestamp": "2026-07-27T00:00:00.000Z",
        "functionCalls": [
            {
                "name": "search_docs",
                "status": "completed",
                "result": [
                    {
                        "chunk_id": "chunk-123",
                        "filename": "doc.pdf",
                        "page": 2,
                        "score": 0.95,
                        "text": "Extracted chunk text",
                        "embedding_model": "text-embedding-3-small",
                        "parser": "Docling",
                        "chunk_size": 512,
                        "chunk_overlap": 64,
                        "source_url": "https://example.com/doc.pdf",
                        "metadata": {"custom_key": "val"},
                        "data": {
                            "file_path": "/path/to/doc.pdf",
                            "page": 2,
                            "score": 0.95,
                            "text": "Extracted chunk text",
                            "embedding_model": "text-embedding-3-small",
                            "parser": "Docling",
                            "chunk_size": 512,
                            "chunk_overlap": 64,
                        },
                    }
                ],
            }
        ],
    }

    msg = AssistantMessage(**payload)
    assert msg.functionCalls is not None
    assert len(msg.functionCalls) == 1
    fc = msg.functionCalls[0]
    assert isinstance(fc, OnboardingFunctionCall)
    assert fc.result is not None
    result = fc.result[0]
    assert result.text == "Extracted chunk text"
    assert result.embedding_model == "text-embedding-3-small"
    assert result.parser == "Docling"
    assert result.chunk_size == 512
    assert result.chunk_overlap == 64
    assert result.source_url == "https://example.com/doc.pdf"
    assert result.metadata == {"custom_key": "val"}
    assert result.data is not None
    assert result.data.text == "Extracted chunk text"


def test_settings_models_accept_arbitrary_provider_credentials():
    credentials = {
        "gemini": {
            "api_key": "secret",
            "vertex_project": "project-1",
            "vertex_location": "us-central1",
        }
    }

    settings = SettingsUpdateBody(
        llm_provider="gemini",
        llm_model="gemini-2.5-pro",
        provider_credentials=credentials,
    )
    onboarding = OnboardingBody(
        llm_provider="gemini",
        llm_model="gemini-2.5-pro",
        provider_credentials=credentials,
    )

    assert settings.provider_credentials == credentials
    assert onboarding.provider_credentials == credentials


def test_custom_provider_payload_keeps_legacy_openai_secret():
    from api.settings.endpoints import _custom_providers_for_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.providers.openai.api_key = "sk-test"
    config.providers.openai.configured = True
    config.providers.set_credentials("openai", {"organization": "org-1"})

    payload = _custom_providers_for_settings(config)
    assert payload["openai"].secret_fields == ["api_key"]
    assert payload["openai"].credential_values["organization"] == "org-1"


@pytest.mark.asyncio
async def test_update_settings_vlm_azure_configured():
    """Test that update_settings allows enabling VLM with azure when azure credentials are configured."""
    from unittest.mock import patch

    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    config.providers.set_credentials(
        "azure", {"api_key": "az-key", "api_base": "https://example.openai.azure.com"}
    )

    body = SettingsUpdateBody(
        vlm_enabled=True,
        vlm_provider="azure",
        vlm_model="azure/gpt-4.1",
    )

    user = MagicMock(spec=User)
    session_manager = AsyncMock()
    models_service = MagicMock()
    models_service.validate_model_configured = AsyncMock(return_value=True)
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.config_manager.save_config_file", return_value=True
        ) as mock_save,
        patch("api.settings.endpoints.clients.refresh_patched_client", new_callable=AsyncMock),
    ):
        response = await update_settings(
            body=body,
            session_manager=session_manager,
            user=user,
            models_service=models_service,
            rbac=rbac,
        )
        assert getattr(response, "status_code", 200) == 200
        mock_save.assert_called_once()
        saved_config = mock_save.call_args[0][0]
        assert saved_config.knowledge.vlm_provider == "azure"
        assert saved_config.knowledge.vlm_model == "azure/gpt-4.1"


@pytest.mark.asyncio
async def test_update_settings_rejects_azure_without_an_api_key():
    """The API must enforce the Azure form requirement, not only the browser."""
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    body = SettingsUpdateBody(
        provider_credentials={"azure": {"api_base": "https://example.openai.azure.com"}},
        provider_auth_methods={"azure": "api_key"},
    )
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with patch("api.settings.endpoints.get_openrag_config", return_value=config):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert response.status_code == 400
    assert b"api_key" in response.body


@pytest.mark.asyncio
async def test_update_settings_validates_azure_credentials_before_saving():
    """A bad Azure endpoint/key must not become a configured provider."""
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    body = SettingsUpdateBody(
        provider_credentials={
            "azure": {
                "api_key": "wrong-key",
                "api_base": "https://example.openai.azure.com",
            }
        },
        provider_auth_methods={"azure": "api_key"},
    )
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
            side_effect=Exception("Access denied due to invalid subscription key"),
        ) as validate,
        patch("api.settings.endpoints.config_manager.save_config_file") as save,
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert response.status_code == 400
    assert b"invalid subscription key" in response.body
    validate.assert_awaited_once()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_update_settings_rejects_invalid_azure_foundry_key_before_saving():
    """The Azure OpenAI form must probe Foundry resource keys on Save too."""
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    body = SettingsUpdateBody(
        provider_credentials={
            "azure": {
                "api_key": "wrong-key",
                "api_base": "https://example.services.ai.azure.com",
            }
        },
        provider_auth_methods={"azure": "api_key"},
    )
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.provider_validation._http_request_with_retry",
            new_callable=AsyncMock,
            return_value=httpx.Response(
                401, json={"error": {"message": "Invalid subscription key"}}
            ),
        ) as request,
        patch("api.settings.endpoints.config_manager.save_config_file") as save,
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert response.status_code == 400
    assert b"Invalid subscription key" in response.body
    request.assert_awaited_once()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_update_settings_validates_enhancement_credentials_before_saving():
    """A credential-only save runs a provider enhancement's model-free check.

    `ProviderSettingsDialog` submits nothing but `provider_credentials`, so the
    `llm_provider` / `embedding_provider` branches never fire. Without a branch
    of its own, a bad OpenShift AI URL or token was stored and the UI reported
    success; the check is handed the untranslated pending form so it sees both
    endpoints, not the one LiteLLM was narrowed to.
    """
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    submitted = {
        "api_base": "https://granite-chat.openrag.svc:8443/v1",
        "embedding_api_base": "https://granite-embed.openrag.svc:8443/v1",
        "api_key": "expired-token",
    }
    body = SettingsUpdateBody(provider_credentials={"rhoai": submitted})
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
            side_effect=Exception("The OpenShift AI chat endpoint rejected the token"),
        ) as validate,
        patch("api.settings.endpoints.config_manager.save_config_file") as save,
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert response.status_code == 400
    assert b"rejected the token" in response.body
    validate.assert_awaited_once()
    kwargs = validate.await_args.kwargs
    assert kwargs["provider"] == "rhoai"
    assert kwargs.get("llm_model") is None and kwargs.get("embedding_model") is None
    assert kwargs["stored_credentials"] == submitted
    save.assert_not_called()


@pytest.mark.asyncio
async def test_update_settings_skips_pre_save_check_for_litellm_only_providers():
    """Providers without an enhancement have no model-free probe to run."""
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    body = SettingsUpdateBody(
        provider_credentials={"openai_like": {"api_base": "https://llm.example", "api_key": "k"}}
    )
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch("api.settings.endpoints.validate_provider_setup", new_callable=AsyncMock) as validate,
        patch("api.settings.endpoints.config_manager.save_config_file"),
        patch("api.settings.endpoints._update_langflow_global_variables", new_callable=AsyncMock),
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert getattr(response, "status_code", 200) == 200
    validate.assert_not_awaited()


@pytest.mark.parametrize(
    "provider",
    ["openai", "watsonx", "anthropic", "local", "ollama", "azure", "azure_ai", "openai_like"],
)
def test_settings_update_body_accepts_configurable_vlm_providers(provider):
    """Any provider key the catalogue can publish must validate.

    `vlm_provider` used to carry a closed enum of the six original providers.
    Every provider added since — `azure_ai` first — 422'd the whole
    ingest-settings save, taking chunk size, OCR and the toggles down with it,
    because the frontend always sends the VLM fields alongside them.
    """
    assert SettingsUpdateBody(vlm_provider=provider).vlm_provider == provider


@pytest.mark.parametrize("provider", ["", "has space", "../etc", "semi;colon"])
def test_settings_update_body_rejects_malformed_vlm_provider(provider):
    with pytest.raises(ValidationError):
        SettingsUpdateBody(vlm_provider=provider)


def test_settings_body_accepts_ocr_languages():
    """OCR languages are settable through the settings API."""
    body = SettingsUpdateBody(ocr_languages=["en", "ja"])

    assert body.ocr_languages == ["ja", "en"]


def test_settings_body_rejects_blank_ocr_language():
    """A blank code would be forwarded to docling and silently break OCR."""
    with pytest.raises(ValidationError):
        SettingsUpdateBody(ocr_languages=["en", "  "])


def test_settings_body_accepts_empty_ocr_language_list():
    """An empty list clears the override so docling uses the engine default."""
    assert SettingsUpdateBody(ocr_languages=[]).ocr_languages == []


def test_settings_body_accepts_one_family_plus_english():
    """A selection drawn from a single recognition-model family is valid."""
    assert SettingsUpdateBody(ocr_languages=["en", "ja"]).ocr_languages == ["ja", "en"]
    assert SettingsUpdateBody(ocr_languages=["ru", "uk"]).ocr_languages == ["ru", "uk"]
    assert SettingsUpdateBody(ocr_languages=["fr", "de", "pt"]).ocr_languages == [
        "fr",
        "de",
        "pt",
    ]


def test_settings_body_rejects_two_restricted_ocr_languages():
    """easyocr cannot serve Japanese and Korean from one recognition model."""
    with pytest.raises(ValidationError):
        SettingsUpdateBody(ocr_languages=["ja", "ko"])


def test_settings_body_rejects_mixed_scripts():
    """Cyrillic and Latin need different easyocr models."""
    with pytest.raises(ValidationError):
        SettingsUpdateBody(ocr_languages=["ru", "fr"])


def test_settings_body_allows_unknown_passthrough_codes():
    """Raw engine codes are the operator's escape hatch; do not second-guess them."""
    assert SettingsUpdateBody(ocr_languages=["hi", "mr"]).ocr_languages == ["hi", "mr"]


@pytest.mark.asyncio
async def test_update_settings_persists_case_insensitive_removal_only_request():
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    config.providers.set_credentials(
        "gemini",
        {"api_key": "secret", "api_base": "https://gemini.example.com"},
    )
    body = SettingsUpdateBody(
        provider_credential_removals={"Gemini": ["api_key"]},
    )
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.config_manager.save_config_file",
            return_value=True,
        ) as save,
        patch(
            "api.settings.endpoints.clients.refresh_patched_client",
            new_callable=AsyncMock,
        ),
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )
    assert getattr(response, "status_code", 200) == 200
    saved_config = save.call_args.args[0]
    assert saved_config.providers.stored_credentials("gemini") == {
        "api_base": "https://gemini.example.com"
    }


@pytest.mark.asyncio
async def test_removal_only_provider_update_requires_provider_write_permission():
    from api.settings.endpoints import update_settings
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.edited = True
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=False)
    rbac.audit_denied = AsyncMock()

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch("api.settings.endpoints.is_rbac_enforced", return_value=True),
        pytest.raises(HTTPException) as exc_info,
    ):
        await update_settings(
            body=SettingsUpdateBody(
                provider_credential_removals={"gemini": ["api_key"]},
            ),
            session_manager=AsyncMock(),
            user=MagicMock(spec=User, db_user_id="user-1", user_id="user-1"),
            models_service=MagicMock(),
            rbac=rbac,
        )

    assert exc_info.value.status_code == 403
    rbac.audit_denied.assert_awaited_once_with("user-1", "providers:write")


@pytest.mark.asyncio
async def test_failed_onboarding_validation_does_not_mutate_cached_config():
    from api.settings.endpoints import onboarding
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.agent.llm_provider = "openai"
    config.agent.llm_model = "old-model"
    body = OnboardingBody(
        llm_provider="openai",
        llm_model="new-model",
        openai_api_key="sk-new",
    )

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.TelemetryClient.send_event",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
            side_effect=Exception("validation failed"),
        ),
    ):
        response = await onboarding(
            body=body,
            flows_service=MagicMock(),
            session_manager=AsyncMock(),
            document_service=MagicMock(),
            models_service=MagicMock(),
            task_service=MagicMock(),
            langflow_file_service=MagicMock(),
            knowledge_filter_service=MagicMock(),
            user=MagicMock(spec=User),
        )

    assert response.status_code == 400
    assert config.agent.llm_model == "old-model"
    assert config.providers.openai.api_key == ""


@pytest.mark.asyncio
async def test_onboarding_validation_receives_onprem_tls_policy():
    from api.settings.endpoints import onboarding
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    body = OnboardingBody(
        llm_provider="watsonx_onprem",
        llm_model="ibm/granite-3-3-8b-instruct",
        provider_credentials={
            "watsonx_onprem": {
                "api_base": "https://cpd.example.com",
                "username": "cpd-user",
                "api_key": "secret",
                "ssl_verify": "false",
            }
        },
        provider_auth_methods={"watsonx_onprem": "username_api_key"},
    )

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.TelemetryClient.send_event",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
            side_effect=Exception("stop after validation arguments are captured"),
        ) as validate,
    ):
        response = await onboarding(
            body=body,
            flows_service=MagicMock(),
            session_manager=AsyncMock(),
            document_service=MagicMock(),
            models_service=MagicMock(),
            task_service=MagicMock(),
            langflow_file_service=MagicMock(),
            knowledge_filter_service=MagicMock(),
            user=MagicMock(spec=User),
        )

    assert response.status_code == 400
    assert validate.await_args.kwargs["stored_credentials"]["ssl_verify"] == "false"


@pytest.mark.asyncio
async def test_onboarding_embedding_validation_receives_onprem_tls_policy():
    from api.settings.endpoints import onboarding
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    body = OnboardingBody(
        embedding_provider="watsonx_onprem",
        embedding_model="ibm/slate-125m-english-rtrvr",
        provider_credentials={
            "watsonx_onprem": {
                "api_base": "https://cpd.example.com",
                "username": "cpd-user",
                "api_key": "secret",
                "ssl_verify": "false",
            }
        },
        provider_auth_methods={"watsonx_onprem": "username_api_key"},
    )

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch(
            "api.settings.endpoints.TelemetryClient.send_event",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
            side_effect=Exception("stop after validation arguments are captured"),
        ) as validate,
    ):
        response = await onboarding(
            body=body,
            flows_service=MagicMock(),
            session_manager=AsyncMock(),
            document_service=MagicMock(),
            models_service=MagicMock(),
            task_service=MagicMock(),
            langflow_file_service=MagicMock(),
            knowledge_filter_service=MagicMock(),
            user=MagicMock(spec=User),
        )

    assert response.status_code == 400
    assert validate.await_args.kwargs["stored_credentials"]["ssl_verify"] == "false"


@pytest.mark.asyncio
async def test_onboarding_caps_chunk_size_for_watsonx_onprem_embeddings():
    from api.settings.endpoints import onboarding
    from config.config_manager import OpenRAGConfig

    config = OpenRAGConfig.from_dict({})
    config.knowledge.chunk_size = 1000
    body = OnboardingBody(
        embedding_provider="watsonx_onprem",
        embedding_model="ibm/slate-30m-english-rtrvr",
        provider_credentials={
            "watsonx_onprem": {
                "api_base": "https://cpd.example.com",
                "username": "cpd-user",
                "api_key": "secret",
                "ssl_verify": "false",
            }
        },
        provider_auth_methods={"watsonx_onprem": "username_api_key"},
    )

    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch("api.settings.endpoints.INGEST_SAMPLE_DATA", False),
        patch(
            "api.settings.endpoints.TelemetryClient.send_event",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.validate_provider_setup",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.wait_for_langflow",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints._update_langflow_global_variables",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints._update_mcp_server_urls",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints._update_langflow_model_values",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.config_manager.save_config_file",
            return_value=True,
        ) as save_config,
        patch(
            "api.settings.endpoints.clients.refresh_patched_client",
            new_callable=AsyncMock,
        ),
        patch(
            "api.settings.endpoints.clients.create_index_admin_opensearch_client",
            return_value=MagicMock(),
        ),
        patch("main.init_index", new_callable=AsyncMock),
    ):
        response = await onboarding(
            body=body,
            flows_service=MagicMock(),
            session_manager=AsyncMock(),
            document_service=MagicMock(),
            models_service=MagicMock(),
            task_service=MagicMock(),
            langflow_file_service=MagicMock(),
            knowledge_filter_service=MagicMock(),
            user=MagicMock(spec=User),
        )

    saved_config = save_config.call_args.args[0]
    assert saved_config.knowledge.chunk_size == 500
    assert response.chunk_size_adjusted_to == 500
