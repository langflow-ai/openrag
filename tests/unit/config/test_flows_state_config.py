"""The applied flow signatures survive a save and reload, and old configs still load."""

import yaml

from config.config_manager import ConfigManager


def test_config_without_flows_section_loads_with_no_signatures(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({"edited": True, "knowledge": {}}), encoding="utf-8")

    config = ConfigManager(config_file=config_file).load_config()

    assert config.flows.applied_signatures == {}


def test_applied_signatures_round_trip_without_marking_config_edited(tmp_path):
    config_file = tmp_path / "config.yaml"
    manager = ConfigManager(config_file=config_file)
    config = manager.load_config()
    assert config.edited is False

    config.flows.applied_signatures["ingest"] = "abc123"
    manager.save_config_file(config, preserve_edited=True)

    reloaded = ConfigManager(config_file=config_file).load_config()
    assert reloaded.flows.applied_signatures == {"ingest": "abc123"}
    assert reloaded.edited is False
