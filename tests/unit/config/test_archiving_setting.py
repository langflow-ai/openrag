"""Unit tests for persistent original-source archiving configuration."""

from pathlib import Path

from config.config_manager import ConfigManager


def test_archiving_defaults_to_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENRAG_ARCHIVE_SOURCES_DEFAULT", raising=False)

    config = ConfigManager(config_file=str(tmp_path / "config.yaml")).load_config()

    assert config.archiving.enabled is False


def test_archiving_environment_default_is_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_ARCHIVE_SOURCES_DEFAULT", "true")

    config = ConfigManager(config_file=str(tmp_path / "config.yaml")).load_config()

    assert config.archiving.enabled is True


def test_archiving_ui_choice_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_ARCHIVE_SOURCES_DEFAULT", "false")
    config_file = Path(tmp_path) / "config.yaml"
    manager = ConfigManager(config_file=str(config_file))
    config = manager.load_config()
    config.archiving.enabled = True
    config.edited = True
    manager.save_config_file(config)

    reloaded = ConfigManager(config_file=str(config_file)).load_config()

    assert reloaded.archiving.enabled is True


def test_archiving_default_upgrades_edited_config_without_archiving_section(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_ARCHIVE_SOURCES_DEFAULT", "true")
    config_file = Path(tmp_path) / "config.yaml"
    config_file.write_text("edited: true\nknowledge: {}\n")

    config = ConfigManager(config_file=str(config_file)).load_config()

    assert config.archiving.enabled is True


def test_archiving_default_does_not_override_saved_ui_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_ARCHIVE_SOURCES_DEFAULT", "true")
    config_file = Path(tmp_path) / "config.yaml"
    config_file.write_text("edited: true\narchiving:\n  enabled: false\n")

    config = ConfigManager(config_file=str(config_file)).load_config()

    assert config.archiving.enabled is False
