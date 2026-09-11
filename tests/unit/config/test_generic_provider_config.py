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


def _clear_rhoai_env(monkeypatch):
    """`.env` is loaded by the root conftest, so competing values must be dropped."""
    for name in (
        "RHOAI_ENDPOINT",
        "RHOAI_EMBEDDINGS_ENDPOINT",
        "RHOAI_API_KEY",
        "RHOAI_TLS_VERIFY",
        "OPENAI_API_KEY",
        "LLM_PROVIDER",
        "EMBEDDING_PROVIDER",
        "LLM_MODEL",
        "EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_rhoai_env_seeds_both_endpoints_and_the_token(monkeypatch, tmp_path):
    """A Helm/operator install has to come up configured without a human clicking
    through Settings, which is the point on an air-gapped cluster."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    monkeypatch.setenv("RHOAI_EMBEDDINGS_ENDPOINT", "https://embed.svc:8443/v1")
    monkeypatch.setenv("RHOAI_API_KEY", "sha256~token")
    monkeypatch.setenv("RHOAI_TLS_VERIFY", "/var/run/secrets/service-ca.crt")

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert config.providers.custom["rhoai"].configured is True
    assert config.providers.stored_credentials("rhoai") == {
        "api_base": "https://chat.svc:8443/v1",
        "embedding_api_base": "https://embed.svc:8443/v1",
        "api_key": "sha256~token",
        "ssl_verify": "/var/run/secrets/service-ca.crt",
    }


def test_rhoai_env_without_a_token_stays_unconfigured(monkeypatch, tmp_path):
    """A provider that reports configured with half a credential set satisfies
    `any_configured()` and can then be picked as a fallback and called with
    nothing useful."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert config.providers.custom["rhoai"].configured is False


def test_rhoai_env_is_ignored_once_settings_have_been_edited(monkeypatch, tmp_path):
    """The trap worth an explicit test: the first Settings save sets
    `config.edited` and silently freezes every environment override, which on a
    declaratively seeded cluster looks like the variables stopped working."""
    import yaml

    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"edited": True}), encoding="utf-8")
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    monkeypatch.setenv("RHOAI_API_KEY", "sha256~token")

    config = ConfigManager(config_file=config_file).load_config()

    assert "rhoai" not in config.providers.custom
