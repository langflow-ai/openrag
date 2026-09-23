"""OPENSEARCH_INDEX_NAME is a role-gated infra setting, not a user preference.

It must resolve to the same value regardless of the ``edited`` flag or which
config loader ran. These tests pin that contract for the yaml-backed
``ConfigManager`` loader (see ``test_workspace_config_service.py`` for the
DB-backed loader).

Regression for issue 81583: chunks were written to the env-configured index
while the connector enrichment path resolved the stale default ``documents``.
"""

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.config_manager import ConfigManager  # noqa: E402


@pytest.fixture
def cfg_file():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "config.yaml"


def test_env_index_name_applies_even_when_config_marked_edited(monkeypatch, cfg_file):
    """A workspace onboarded through the UI has ``edited: true``; the env
    override for the index name must still win."""
    cfg_file.write_text(yaml.safe_dump({"edited": True, "knowledge": {}}))
    monkeypatch.setenv("OPENSEARCH_INDEX_NAME", "orag-documents")

    cm = ConfigManager(config_file=str(cfg_file))
    config = cm.load_config()

    assert config.knowledge.index_name == "orag-documents"


def test_env_index_name_absent_keeps_stored_value(monkeypatch, cfg_file):
    cfg_file.write_text(
        yaml.safe_dump({"edited": True, "knowledge": {"index_name": "team-documents"}})
    )
    monkeypatch.delenv("OPENSEARCH_INDEX_NAME", raising=False)

    cm = ConfigManager(config_file=str(cfg_file))
    config = cm.load_config()

    assert config.knowledge.index_name == "team-documents"


def test_env_index_name_not_permitted_is_ignored(monkeypatch, cfg_file):
    """A value outside the OpenSearch security role's index patterns is
    rejected, keeping the prior value rather than breaking access."""
    cfg_file.write_text(yaml.safe_dump({"edited": True, "knowledge": {"index_name": "documents"}}))
    monkeypatch.setenv("OPENSEARCH_INDEX_NAME", "totally-different-name")

    cm = ConfigManager(config_file=str(cfg_file))
    config = cm.load_config()

    assert config.knowledge.index_name == "documents"
