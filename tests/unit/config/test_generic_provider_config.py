from config.config_manager import OpenRAGConfig


def test_arbitrary_provider_credentials_round_trip():
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials(
        "gemini",
        {
            "api_key": "secret",
            "vertex_project": "project-1",
            "vertex_location": "us-central1",
        },
    )

    loaded = OpenRAGConfig.from_dict(config.to_dict())

    assert loaded.providers.custom["gemini"].configured is True
    assert loaded.providers.credential_values("gemini") == {
        "api_key": "secret",
        "vertex_project": "project-1",
        "vertex_location": "us-central1",
    }


def test_legacy_provider_keeps_extra_catalog_fields():
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials(
        "openai",
        {
            "api_key": "secret",
            "api_base": "https://gateway.example/v1",
            "organization": "org-1",
        },
    )

    assert config.providers.openai.api_key == "secret"
    assert config.providers.credential_values("openai") == {
        "api_key": "secret",
        "api_base": "https://gateway.example/v1",
        "organization": "org-1",
    }


def test_blank_credentials_do_not_register_a_configured_provider():
    """A submission with no usable values must not create a phantom provider.

    `any_configured()` gates the settings API, and the fallback provider
    helpers pick the first configured entry — a provider marked configured with
    zero credentials would be selected and then called with no key at all.
    """
    config = OpenRAGConfig.from_dict({})

    config.providers.set_credentials("gemini", {"api_key": "   ", "": "x"})

    assert "gemini" not in config.providers.custom
    assert config.providers.any_configured() is False


def test_blank_credentials_leave_an_existing_provider_untouched():
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials("gemini", {"api_key": "secret"})

    config.providers.set_credentials("gemini", {"api_key": ""})

    assert config.providers.custom["gemini"].configured is True
    assert config.providers.credential_values("gemini") == {"api_key": "secret"}


def test_azure_openai_env_overrides_and_defaults(monkeypatch, tmp_path):
    from config.config_manager import ConfigManager

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test-azure.openai.azure.com")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    cm = ConfigManager(config_file=tmp_path / "config.yaml")
    config = cm.load_config()

    assert config.providers.custom["azure"].configured is True
    assert config.providers.credential_values("azure") == {
        "api_key": "test-azure-key",
        "api_base": "https://test-azure.openai.azure.com",
    }
    assert config.agent.llm_provider == "azure"
    assert config.agent.llm_model == "gpt-4.1"
    assert config.knowledge.embedding_provider == "azure"
    assert config.knowledge.embedding_model == "text-embedding-3-small"


def test_azure_openai_env_does_not_configure_azure_ai_foundry(monkeypatch, tmp_path):
    """Foundry is a separate resource, so Azure OpenAI's keys must not claim it.

    Seeding both from `AZURE_OPENAI_*` made Foundry look configured whenever
    Azure OpenAI was, which put its catalogue (Mistral, Llama, Phi …) in the
    model pickers — and auto-selected one of those for picture descriptions —
    against an endpoint that serves none of them.
    """
    from config.config_manager import ConfigManager

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://test-azure.openai.azure.com")
    for name in ("AZURE_AI_API_KEY", "AZURE_AI_API_BASE", "AZURE_AI_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)

    cm = ConfigManager(config_file=tmp_path / "config.yaml")
    config = cm.load_config()

    assert config.providers.custom["azure"].configured is True
    assert "azure_ai" not in config.providers.custom


def test_azure_ai_foundry_env_configures_only_foundry(monkeypatch, tmp_path):
    from config.config_manager import ConfigManager

    monkeypatch.setenv("AZURE_AI_API_KEY", "foundry-key")
    monkeypatch.setenv("AZURE_AI_API_BASE", "https://test.services.ai.azure.com/models")
    for name in (
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_BASE",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
    ):
        monkeypatch.delenv(name, raising=False)

    cm = ConfigManager(config_file=tmp_path / "config.yaml")
    config = cm.load_config()

    assert config.providers.custom["azure_ai"].configured is True
    assert config.providers.credential_values("azure_ai") == {
        "api_key": "foundry-key",
        "api_base": "https://test.services.ai.azure.com/models",
    }
    assert "azure" not in config.providers.custom
