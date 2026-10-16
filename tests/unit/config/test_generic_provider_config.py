import pytest

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
        "RHOAI_EMBEDDING_MAX_CONCURRENCY",
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


def test_rhoai_tls_env_alone_reaches_a_stored_config(monkeypatch, tmp_path):
    """A CA path mounted in a later rollout arrives as `RHOAI_TLS_VERIFY` on its
    own, against a config that already holds the endpoint and token. It has to
    land, and it must not disturb `configured`."""
    import yaml

    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "custom": {
                        "rhoai": {
                            "credentials": {
                                "api_base": "https://chat.svc:8443/v1",
                                "api_key": "sha256~token",
                            },
                            "configured": True,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RHOAI_TLS_VERIFY", "/var/run/secrets/service-ca.crt")

    config = ConfigManager(config_file=config_file).load_config()

    assert config.providers.custom["rhoai"].configured is True
    assert config.providers.stored_credentials("rhoai") == {
        "api_base": "https://chat.svc:8443/v1",
        "api_key": "sha256~token",
        "ssl_verify": "/var/run/secrets/service-ca.crt",
    }


def test_rhoai_embedding_concurrency_env_is_seeded(monkeypatch, tmp_path):
    """The bulkhead limit ships with the rest of the provider's first-boot seed."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    monkeypatch.setenv("RHOAI_API_KEY", "sha256~token")
    monkeypatch.setenv("RHOAI_EMBEDDING_MAX_CONCURRENCY", "8")

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert config.providers.custom["rhoai"].configured is True
    assert config.providers.stored_credentials("rhoai")["embedding_max_concurrency"] == "8"


def test_rhoai_env_credentials_accessor_maps_env_names_to_fields(monkeypatch):
    """Each RHOAI_* variable lands under the credential field the enhancement reads."""
    from config.settings import get_rhoai_env_credentials

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    monkeypatch.setenv("RHOAI_EMBEDDINGS_ENDPOINT", "https://embed.svc:8443/v1")
    monkeypatch.setenv("RHOAI_API_KEY", "sha256~token")
    monkeypatch.setenv("RHOAI_TLS_VERIFY", "/var/run/secrets/service-ca.crt")
    monkeypatch.setenv("RHOAI_EMBEDDING_MAX_CONCURRENCY", "6")

    assert get_rhoai_env_credentials() == {
        "api_base": "https://chat.svc:8443/v1",
        "embedding_api_base": "https://embed.svc:8443/v1",
        "api_key": "sha256~token",
        "ssl_verify": "/var/run/secrets/service-ca.crt",
        "embedding_max_concurrency": "6",
    }


def test_rhoai_seed_is_read_through_settings_boundary(monkeypatch, tmp_path):
    """Seeding goes through `config.settings`, and stores values unvalidated: an
    invalid concurrency limit is the enhancement's to reject (default + warning)."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setattr(
        "config.settings.get_rhoai_env_credentials",
        lambda: {
            "api_base": "https://chat.svc:8443/v1",
            "embedding_api_base": None,
            "api_key": "sha256~token",
            "ssl_verify": None,
            "embedding_max_concurrency": "not-a-number",
        },
    )

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert config.providers.custom["rhoai"].configured is True
    assert config.providers.stored_credentials("rhoai") == {
        "api_base": "https://chat.svc:8443/v1",
        "api_key": "sha256~token",
        "embedding_max_concurrency": "not-a-number",
    }


def test_rhoai_is_not_seeded_when_no_env_is_set(monkeypatch, tmp_path):
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert "rhoai" not in config.providers.custom


def _clear_watsonx_onprem_env(monkeypatch):
    for name in (
        "WATSONX_ENDPOINT_ONPREM",
        "WATSONX_USERNAME_ONPREM",
        "WATSONX_API_KEY_ONPREM",
        "WATSONX_ZEN_API_KEY_ONPREM",
        "WATSONX_SPACE_ID_ONPREM",
        "WATSONX_PROJECT_ID_ONPREM",
        "WATSONX_TLS_VERIFY_ONPREM",
    ):
        monkeypatch.delenv(name, raising=False)


def test_watsonx_onprem_env_seeds_credentials_and_tls(monkeypatch, tmp_path):
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    _clear_watsonx_onprem_env(monkeypatch)
    monkeypatch.setenv("WATSONX_ENDPOINT_ONPREM", "https://cpd.example.com")
    monkeypatch.setenv("WATSONX_USERNAME_ONPREM", "cpduser")
    monkeypatch.setenv("WATSONX_API_KEY_ONPREM", "secret")
    monkeypatch.setenv("WATSONX_SPACE_ID_ONPREM", "space-1")
    monkeypatch.setenv("WATSONX_PROJECT_ID_ONPREM", "project-1")
    monkeypatch.setenv("WATSONX_TLS_VERIFY_ONPREM", "/etc/openrag/cpd-ca.pem")

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()
    provider = config.providers.custom["watsonx_onprem"]

    assert provider.configured is True
    assert provider.auth_method == "username_api_key"
    assert config.providers.stored_credentials("watsonx_onprem") == {
        "api_base": "https://cpd.example.com",
        "username": "cpduser",
        "api_key": "secret",
        "space_id": "space-1",
        "project_id": "project-1",
        "ssl_verify": "/etc/openrag/cpd-ca.pem",
    }


def test_watsonx_onprem_env_without_complete_auth_stays_unconfigured(monkeypatch, tmp_path):
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    _clear_watsonx_onprem_env(monkeypatch)
    monkeypatch.setenv("WATSONX_ENDPOINT_ONPREM", "https://cpd.example.com")
    monkeypatch.setenv("WATSONX_TLS_VERIFY_ONPREM", "false")

    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    assert config.providers.custom["watsonx_onprem"].configured is False


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


def test_pending_stored_credentials_overlays_the_submission_on_the_stored_form(
    monkeypatch, tmp_path
):
    """The pre-save health check of a two-endpoint provider needs the raw form
    as it will read once saved: what is stored, with the request's non-blank
    fields on top, and nothing translated away."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    monkeypatch.setenv("RHOAI_EMBEDDINGS_ENDPOINT", "https://embed.svc:8443/v1")
    monkeypatch.setenv("RHOAI_API_KEY", "sha256~token")
    config = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    pending = config.providers.pending_stored_credentials(
        "rhoai",
        {
            "embedding_api_base": " https://new-embed.svc:8443/v1 ",
            # A changed endpoint needs the token re-entered (see the
            # credential-target tests below).
            "api_key": "sha256~new-token",
            "ssl_verify": "  ",
        },
    )

    assert pending == {
        "api_base": "https://chat.svc:8443/v1",
        "embedding_api_base": "https://new-embed.svc:8443/v1",
        "api_key": "sha256~new-token",
    }
    # Pending, not saved.
    assert config.providers.stored_credentials("rhoai")["embedding_api_base"] == (
        "https://embed.svc:8443/v1"
    )


def test_a_partial_save_does_not_mark_a_provider_configured():
    """`configured` gates `any_configured()` and the fallback-provider pick, so
    a direct API save of just `ssl_verify` must not make `rhoai` look callable:
    `litellm_credentials()` would return `{}` for it and LiteLLM would fall back
    to whatever `HOSTED_VLLM_API_BASE` is in the environment."""
    config = OpenRAGConfig.from_dict({})

    config.providers.set_credentials("rhoai", {"ssl_verify": "false"})

    assert config.providers.custom["rhoai"].configured is False
    assert config.providers.any_configured() is False
    # The value is kept, so a later save that completes the set builds on it.
    assert config.providers.stored_credentials("rhoai") == {"ssl_verify": "false"}


def test_a_save_that_completes_the_required_fields_configures_the_provider():
    """The check is against the merged credentials, not the one submission, so
    a form saved in two steps ends up configured once every required field is in."""
    config = OpenRAGConfig.from_dict({})

    config.providers.set_credentials("rhoai", {"api_base": "https://chat.svc:8443/v1"})
    assert config.providers.custom["rhoai"].configured is False

    config.providers.set_credentials("rhoai", {"api_key": "sha256~token"})
    assert config.providers.custom["rhoai"].configured is True


def test_a_provider_without_required_fields_is_configured_by_any_credential():
    """Providers whose spec marks nothing required keep the old "any non-empty
    credential" rule — Anthropic's form, for one, marks neither field."""
    config = OpenRAGConfig.from_dict({})

    config.providers.set_credentials("anthropic", {"api_base": "https://proxy.example"})

    assert config.providers.custom["anthropic"].configured is True


def test_the_settings_save_and_the_env_seed_agree_on_configured(monkeypatch, tmp_path):
    """Both write paths run the same completeness check, so a provider cannot
    be unconfigured from the environment yet configured from the same fields
    entered in Settings, or the reverse."""
    from config.config_manager import ConfigManager

    _clear_rhoai_env(monkeypatch)
    monkeypatch.setenv("RHOAI_ENDPOINT", "https://chat.svc:8443/v1")
    seeded = ConfigManager(config_file=tmp_path / "config.yaml").load_config()

    saved = OpenRAGConfig.from_dict({})
    saved.providers.set_credentials("rhoai", {"api_base": "https://chat.svc:8443/v1"})

    assert seeded.providers.custom["rhoai"].configured is False
    assert saved.providers.custom["rhoai"].configured is False


# --- Credential targets ------------------------------------------------------
#
# A secret is never echoed to a form, so a blank secret means "keep the saved
# one". That is only safe while the credentials still go where they went when it
# was saved: once `api_base`, `embedding_api_base` or `ssl_verify` changes, a
# kept token would be sent to the new host. The save, and the pre-save probe,
# refuse instead.

_RHOAI_SAVED = {
    "api_base": "https://chat.host-a:8443/v1",
    "embedding_api_base": "https://embed.host-a:8443/v1",
    "api_key": "sha256~host-a-token",
    "ssl_verify": "true",
}


def _rhoai_config() -> OpenRAGConfig:
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials("rhoai", dict(_RHOAI_SAVED))
    return config


@pytest.mark.parametrize(
    ("submitted", "remove"),
    [
        ({"api_base": "https://chat.host-b:8443/v1"}, set()),
        ({"embedding_api_base": "https://embed.host-b:8443/v1"}, set()),
        ({"ssl_verify": "false"}, set()),
        ({}, {"ssl_verify"}),
    ],
    ids=["api_base", "embedding_api_base", "ssl_verify", "ssl_verify-cleared"],
)
def test_a_changed_target_without_the_secret_is_refused_and_nothing_changes(submitted, remove):
    from config.config_manager import CredentialTargetChangedError

    config = _rhoai_config()

    with pytest.raises(CredentialTargetChangedError) as exc_info:
        config.providers.set_credentials("rhoai", submitted, remove=remove)

    assert exc_info.value.fields == ("api_key",)
    # Client-safe: names the form label, never a value.
    assert "ServiceAccount token" in str(exc_info.value)
    assert "host-a-token" not in str(exc_info.value)
    assert config.providers.stored_credentials("rhoai") == _RHOAI_SAVED
    assert config.providers.custom["rhoai"].configured is True


def test_the_same_target_keeps_the_saved_secret():
    config = _rhoai_config()

    config.providers.set_credentials(
        "rhoai",
        {
            # Resubmitted unchanged (the form pre-fills non-secrets) — not a change.
            "api_base": " https://chat.host-a:8443/v1 ",
            "embedding_max_concurrency": "4",
        },
    )

    assert config.providers.stored_credentials("rhoai")["api_key"] == "sha256~host-a-token"


def test_a_changed_target_with_the_secret_re_entered_is_saved():
    config = _rhoai_config()

    config.providers.set_credentials(
        "rhoai",
        {"api_base": "https://chat.host-b:8443/v1", "api_key": "sha256~host-b-token"},
    )

    stored = config.providers.stored_credentials("rhoai")
    assert stored["api_base"] == "https://chat.host-b:8443/v1"
    assert stored["api_key"] == "sha256~host-b-token"


def test_a_changed_target_with_the_secret_removed_is_saved_unconfigured():
    """Removing the secret is the other explicit answer: nothing is reused."""
    config = _rhoai_config()

    config.providers.set_credentials(
        "rhoai", {"api_base": "https://chat.host-b:8443/v1"}, remove={"api_key"}
    )

    assert "api_key" not in config.providers.stored_credentials("rhoai")
    assert config.providers.custom["rhoai"].configured is False


@pytest.mark.parametrize("kind", ["chat", "embedding"])
def test_the_pre_save_probe_never_gets_the_stale_secret(kind):
    """Validation runs before the write, so it must refuse on the same terms —
    otherwise the probe itself sends host A's token to host B."""
    from config.config_manager import CredentialTargetChangedError

    config = _rhoai_config()
    submitted = {"api_base": "https://chat.host-b:8443/v1"}

    with pytest.raises(CredentialTargetChangedError):
        config.providers.pending_stored_credentials("rhoai", submitted)
    with pytest.raises(CredentialTargetChangedError):
        config.providers.pending_credentials("rhoai", submitted, kind=kind)


def test_a_generic_provider_probe_is_refused_too():
    """Azure is not an enhancement: its call kwargs are its stored form."""
    from config.config_manager import CredentialTargetChangedError

    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials(
        "azure",
        {"api_base": "https://a.openai.azure.com", "api_key": "azure-key"},
        auth_method="api_key",
    )

    with pytest.raises(CredentialTargetChangedError):
        config.providers.pending_credentials(
            "azure", {"api_base": "https://b.openai.azure.com"}, auth_method="api_key"
        )
    with pytest.raises(CredentialTargetChangedError):
        config.providers.set_credentials(
            "azure", {"api_base": "https://b.openai.azure.com"}, auth_method="api_key"
        )
    assert config.providers.stored_credentials("azure")["api_base"] == (
        "https://a.openai.azure.com"
    )


def test_switching_auth_method_with_a_new_target_drops_the_inactive_secret():
    """The old method's secret is not reused (it is out of scope for the new
    method) and must not reach the probe either."""
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials(
        "azure",
        {"api_base": "https://a.openai.azure.com", "api_key": "azure-key"},
        auth_method="api_key",
    )
    submitted = {"api_base": "https://b.openai.azure.com", "azure_ad_token": "entra-token"}

    probe = config.providers.pending_credentials("azure", submitted, auth_method="entra_token")
    config.providers.set_credentials("azure", submitted, auth_method="entra_token")

    assert "api_key" not in probe
    assert config.providers.stored_credentials("azure") == submitted


def test_first_class_providers_are_exempt():
    """An IBM Cloud API key is valid in every watsonx.ai region, so switching
    region with the saved key is legitimate; the bespoke forms never promise
    otherwise."""
    config = OpenRAGConfig.from_dict({})
    config.providers.set_credentials(
        "watsonx",
        {"api_base": "https://us-south.ml.cloud.ibm.com", "api_key": "ibm-key"},
    )

    config.providers.set_credentials("watsonx", {"api_base": "https://eu-de.ml.cloud.ibm.com"})

    assert config.providers.credential_values("watsonx")["api_key"] == "ibm-key"


def test_an_unreadable_form_spec_fails_closed(monkeypatch):
    """Without the spec every stored non-target field may be a secret."""
    import services.model_catalog as model_catalog
    from config.config_manager import CredentialTargetChangedError

    config = _rhoai_config()

    def _broken(_provider):
        raise RuntimeError("catalogue unavailable")

    monkeypatch.setattr(model_catalog, "credential_fields", _broken)

    with pytest.raises(CredentialTargetChangedError) as exc_info:
        config.providers.set_credentials("rhoai", {"api_base": "https://chat.host-b:8443/v1"})
    assert exc_info.value.fields == ("api_key",)


def test_discovery_and_save_share_one_target_rule():
    """`_draft_credentials` (model discovery) reuses the save's rule, so the
    UI's discovery never offers a secret the save then refuses."""
    from config.config_manager import retargeted_credential_fields

    stored = {"api_base": "https://a", "ssl_verify": "true"}

    assert retargeted_credential_fields(stored, {"api_base": "https://a"}, set()) == []
    assert retargeted_credential_fields(stored, {"api_base": "https://b"}, set()) == ["api_base"]
    assert retargeted_credential_fields(stored, {}, {"ssl_verify"}) == ["ssl_verify"]
    # Clearing something that was never stored is not a change.
    assert retargeted_credential_fields(stored, {}, {"embedding_api_base"}) == []
