from pathlib import Path

from config.config_manager import ConfigManager


def test_config_manager_uses_openrag_config_path(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENRAG_CONFIG_FILE", raising=False)
    monkeypatch.setenv("OPENRAG_CONFIG_PATH", str(tmp_path))

    config_manager = ConfigManager()

    assert config_manager.config_file == tmp_path / "config.yaml"


def test_config_manager_prefers_explicit_config_file_env(monkeypatch, tmp_path):
    explicit_config_file = tmp_path / "custom-config.yaml"
    monkeypatch.setenv("OPENRAG_CONFIG_PATH", str(tmp_path / "ignored"))
    monkeypatch.setenv("OPENRAG_CONFIG_FILE", str(explicit_config_file))

    config_manager = ConfigManager()

    assert config_manager.config_file == explicit_config_file
