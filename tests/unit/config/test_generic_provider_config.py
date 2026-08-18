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
