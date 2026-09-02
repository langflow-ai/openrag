from config.config_manager import BomaRAGConfig


def test_arbitrary_provider_credentials_round_trip():
    config = BomaRAGConfig.from_dict({})
    config.providers.set_credentials(
        "gemini",
        {
            "api_key": "secret",
            "vertex_project": "project-1",
            "vertex_location": "us-central1",
        },
    )

    loaded = BomaRAGConfig.from_dict(config.to_dict())

    assert loaded.providers.custom["gemini"].configured is True
    assert loaded.providers.credential_values("gemini") == {
        "api_key": "secret",
        "vertex_project": "project-1",
        "vertex_location": "us-central1",
    }


def test_legacy_provider_keeps_extra_catalog_fields():
    config = BomaRAGConfig.from_dict({})
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
    config = BomaRAGConfig.from_dict({})

    config.providers.set_credentials("gemini", {"api_key": "   ", "": "x"})

    assert "gemini" not in config.providers.custom
    assert config.providers.any_configured() is False


def test_blank_credentials_leave_an_existing_provider_untouched():
    config = BomaRAGConfig.from_dict({})
    config.providers.set_credentials("gemini", {"api_key": "secret"})

    config.providers.set_credentials("gemini", {"api_key": ""})

    assert config.providers.custom["gemini"].configured is True
    assert config.providers.credential_values("gemini") == {"api_key": "secret"}
