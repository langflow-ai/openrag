"""Path-safety coverage for ``ConfigManager``.

The config file path is validated against a strict allowlist (safe characters,
no traversal, must end in .yaml/.yml) before it ever reaches a filesystem sink
(open/mkdir). These tests pin that behavior so the SonarQube taint remediation
does not regress.
"""

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.config_manager import ConfigManager  # noqa: E402


def test_constructor_rejects_traversal():
    with pytest.raises(ValueError):
        ConfigManager(config_file="config/../etc/config.yaml")


def test_setter_rejects_control_characters():
    with tempfile.TemporaryDirectory() as tmp:
        cm = ConfigManager(config_file=str(Path(tmp) / "config.yaml"))
        with pytest.raises(ValueError):
            cm.config_file = "config/evil\nname.yaml"


def test_setter_rejects_shell_metacharacters():
    with tempfile.TemporaryDirectory() as tmp:
        cm = ConfigManager(config_file=str(Path(tmp) / "config.yaml"))
        with pytest.raises(ValueError):
            cm.config_file = "config/$(touch x).yaml"


def test_non_yaml_target_is_rejected():
    with pytest.raises(ValueError):
        ConfigManager(config_file="config/passwd")


def test_valid_path_is_accepted_and_usable():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))

        assert isinstance(cm.config_file, Path)

        # Round-trip: save then reload still works on the validated path.
        assert cm.save_config_file() is True
        assert cm.config_file.exists()
        cm.reload_config()
