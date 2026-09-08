import json

from config.config_manager import ConfigManager


def test_operator_can_supply_legacy_embedding_provider_map_from_environment(monkeypatch, tmp_path):
    mapping = {
        "ibm/slate-125m-english-rtrvr": "watsonx",
        "custom-embed": "azure",
    }
    monkeypatch.setenv("OPENRAG_LEGACY_EMBEDDING_PROVIDER_MAP", json.dumps(mapping))

    config = ConfigManager(str(tmp_path / "config.yaml")).load_config()

    assert config.knowledge.legacy_embedding_provider_map == mapping


def test_operator_legacy_map_applies_after_settings_have_been_edited(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("edited: true\nknowledge: {}\n", encoding="utf-8")
    monkeypatch.setenv(
        "OPENRAG_LEGACY_EMBEDDING_PROVIDER_MAP",
        '{"ibm/slate-125m-english-rtrvr":"watsonx"}',
    )

    config = ConfigManager(str(config_path)).load_config()

    assert config.knowledge.legacy_embedding_provider_map == {
        "ibm/slate-125m-english-rtrvr": "watsonx"
    }


def test_legacy_map_is_read_through_settings_boundary(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENRAG_LEGACY_EMBEDDING_PROVIDER_MAP", raising=False)
    monkeypatch.setattr(
        "config.settings.get_legacy_embedding_provider_map_json",
        lambda: '{"custom-embed":"azure"}',
    )

    config = ConfigManager(str(tmp_path / "config.yaml")).load_config()

    assert config.knowledge.legacy_embedding_provider_map == {"custom-embed": "azure"}
