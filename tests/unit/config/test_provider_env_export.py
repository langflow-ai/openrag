"""Provider credentials must reach LiteLLM through the environment too.

The agentd-patched OpenAI client — used by langflowless ingest and chat —
forwards only `model`, `input` and a dynamic `api_key` to LiteLLM. There is no
kwargs channel for `api_base`, so a provider that needs more than a key (Azure
requires `api_base` and raises "No API Base provided" without it) can only be
reached through environment variables. These tests pin the names.
"""

import pytest

from config.config_manager import OpenRAGConfig
from config.settings import provider_env_vars


def _config(custom: dict) -> OpenRAGConfig:
    return OpenRAGConfig.from_dict({"providers": {"custom": custom}})


def _azure(**credentials) -> dict:
    return {"azure": {"credentials": credentials, "configured": True}}


def test_azure_exports_the_api_base_that_was_missing():
    """The reported bug: ingestion died on `Set 'AZURE_API_BASE' in .env`."""
    env = provider_env_vars(
        _config(
            _azure(
                api_key="sk-azure",
                api_base="https://resource.openai.azure.com",
                api_version="2024-10-21",
            )
        )
    )

    assert env["AZURE_API_BASE"] == "https://resource.openai.azure.com"
    assert env["AZURE_API_KEY"] == "sk-azure"
    assert env["AZURE_API_VERSION"] == "2024-10-21"


def test_foundry_uses_its_own_prefix():
    """`azure_ai` is a separate LiteLLM route reading separate variables."""
    env = provider_env_vars(
        _config(
            {
                "azure_ai": {
                    "credentials": {
                        "api_key": "foundry-key",
                        "api_base": "https://x.services.ai.azure.com",
                    },
                    "configured": True,
                }
            }
        )
    )

    assert env["AZURE_AI_API_BASE"] == "https://x.services.ai.azure.com"
    assert env["AZURE_AI_API_KEY"] == "foundry-key"
    # The two routes must not collide.
    assert "AZURE_API_BASE" not in env


def test_an_aliased_provider_exports_under_its_canonical_prefix():
    env = provider_env_vars(
        _config(
            {
                "azure_ai_foundry": {
                    "credentials": {"api_key": "k", "api_base": "https://x"},
                    "configured": True,
                }
            }
        )
    )

    assert env["AZURE_AI_API_KEY"] == "k"
    assert not [name for name in env if name.startswith("AZURE_AI_FOUNDRY")]


@pytest.mark.parametrize(
    "credential,expected",
    [
        # LiteLLM reads AZURE_AD_TOKEN and AZURE_TENANT_ID — a naive
        # f"{PREFIX}_{FIELD}" join would double the prefix and be ignored.
        ("azure_ad_token", "AZURE_AD_TOKEN"),
        ("tenant_id", "AZURE_TENANT_ID"),
        ("client_secret", "AZURE_CLIENT_SECRET"),
    ],
)
def test_fields_carrying_the_provider_prefix_are_not_prefixed_twice(credential, expected):
    env = provider_env_vars(_config(_azure(**{credential: "value"})))

    assert expected in env
    assert "AZURE_AZURE_AD_TOKEN" not in env


def test_unknown_credential_fields_are_exported_too():
    """No allowlist: dropping unrecognised fields is what caused this bug."""
    env = provider_env_vars(_config({"vertex_ai": {"credentials": {"vertex_location": "us"}}}))

    assert env["VERTEX_AI_VERTEX_LOCATION"] == "us"


def test_blank_and_empty_providers_export_nothing():
    assert provider_env_vars(_config(_azure(api_key="   "))) == {}
    assert provider_env_vars(_config({"azure": {"credentials": {}}})) == {}
    assert provider_env_vars(_config({})) == {}


def test_config_values_win_over_ambient_env(monkeypatch):
    """Deliberate precedence: the gateway route passes config credentials as
    explicit kwargs, which beat env inside LiteLLM. If `.env` won here the two
    routes could resolve to different endpoints — the bug being fixed.
    """
    monkeypatch.setenv("AZURE_API_BASE", "https://stale-from-dotenv")

    env = provider_env_vars(_config(_azure(api_base="https://from-config")))

    assert env["AZURE_API_BASE"] == "https://from-config"


def test_credential_values_are_never_logged(caplog):
    secret = "sk-do-not-log-me"

    with caplog.at_level("DEBUG"):
        provider_env_vars(_config(_azure(api_key=secret, api_base="https://r")))

    assert secret not in caplog.text
