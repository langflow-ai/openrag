"""`azure_ai_foundry` and friends must resolve to the key LiteLLM knows.

Provider names arrive from onboarding bodies, `.env`, saved config and model
ids, and each of those used to normalize with its own `.strip().lower()`. An
alias honoured on only some of those paths is worse than none — the write path
stores under one key while the read path looks under another. `canonical_provider`
is the single normalizer; these tests pin that it is applied on both sides.
"""

import pytest

from config.config_manager import OpenRAGConfig
from config.model_providers import canonical_provider


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("azure_ai_foundry", "azure_ai"),
        ("  Azure_AI_Foundry ", "azure_ai"),
        ("AZURE_AI_FOUNDRY", "azure_ai"),
        # Real keys pass through untouched, only normalized.
        ("azure", "azure"),
        ("Azure", "azure"),
        ("azure_ai", "azure_ai"),
        ("  OpenAI  ", "openai"),
        # Unknown names are lowercased, not rejected — the gateway reports
        # "not configured" with a useful message downstream.
        ("some-new-provider", "some-new-provider"),
        (None, ""),
        ("", ""),
    ],
)
def test_canonical_provider(raw, expected):
    assert canonical_provider(raw) == expected


def test_credentials_stored_under_an_alias_are_found_under_the_canonical_key():
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials("azure_ai_foundry", {"api_key": "k", "api_base": "https://x"})

    assert config.providers.credential_values("azure_ai") == {
        "api_key": "k",
        "api_base": "https://x",
    }
    # And the alias still resolves, so an unmigrated caller keeps working.
    assert config.providers.credential_values("azure_ai_foundry")["api_base"] == "https://x"
    assert list(config.providers.custom) == ["azure_ai"]


def test_a_config_saved_under_an_alias_migrates_on_load():
    """No separate migration step: loading rewrites the key."""
    config = OpenRAGConfig.from_dict(
        {
            "providers": {
                "custom": {
                    "azure_ai_foundry": {
                        "credentials": {"api_key": "k", "api_base": "https://x"},
                        "configured": True,
                    }
                }
            },
            "agent": {"llm_provider": "azure_ai_foundry"},
            "knowledge": {"embedding_provider": "AZURE_AI_FOUNDRY"},
        }
    )

    assert list(config.providers.custom) == ["azure_ai"]
    assert config.agent.llm_provider == "azure_ai"
    assert config.knowledge.embedding_provider == "azure_ai"


def test_alias_and_canonical_keys_are_merged_rather_than_one_overwriting():
    config = OpenRAGConfig.from_dict(
        {
            "providers": {
                "custom": {
                    "azure_ai_foundry": {
                        "credentials": {"api_base": "https://from-alias", "api_key": "alias-key"},
                        "configured": True,
                    },
                    "azure_ai": {
                        "credentials": {"api_key": "canonical-key"},
                        "configured": True,
                    },
                }
            }
        }
    )

    credentials = config.providers.credential_values("azure_ai")
    # The canonical entry wins on conflict, but the alias-only field survives.
    assert credentials["api_key"] == "canonical-key"
    assert credentials["api_base"] == "https://from-alias"


def test_get_provider_config_resolves_the_alias():
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials("azure_ai_foundry", {"api_key": "k"})

    assert config.providers.get_provider_config("azure_ai_foundry").configured is True
    assert config.providers.get_provider_config("azure_ai").configured is True
