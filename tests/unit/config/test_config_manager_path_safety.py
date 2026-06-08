"""Path-safety coverage for ``ConfigManager``.

The config file path is canonicalized and validated against directory-traversal
tokens before it ever reaches a filesystem sink (open/mkdir). These tests pin
that behavior so the SonarQube taint remediation does not regress.
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
        ConfigManager(config_file="some/../etc/config.yaml")


def test_setter_rejects_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        cm = ConfigManager(config_file=str(Path(tmp) / "config.yaml"))
        with pytest.raises(ValueError):
            cm.config_file = "../escape/config.yaml"


def test_normal_path_is_canonicalized_and_usable():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_file = Path(tmp) / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_file))

        # Stored path is an absolute, resolved Path free of traversal tokens.
        assert isinstance(cm.config_file, Path)
        assert cm.config_file.is_absolute()
        assert ".." not in cm.config_file.parts

        # Round-trip: save then reload still works on the canonical path.
        assert cm.save_config_file() is True
        assert cm.config_file.exists()
        cm.reload_config()
