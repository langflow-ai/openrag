"""Tests for the FileNet P8 MCP chat-tool feature flags and availability gate.

Gate semantics (mirrors the Azure Blob connector pattern):

    available = OPENRAG_FILENET_MCP_ENABLED            (kill switch, default true)
                AND (run mode == on_prem
                     OR OPENRAG_DEV_FILENET_MCP)       (enterprise gate / dev bypass)
                AND OPENRAG_FILENET_MCP_URL non-empty  (configuration present)
"""

import pytest

from config.settings import (
    FILENET_MCP_SERVER_NAME,
    get_filenet_mcp_token,
    get_filenet_mcp_url,
    get_filenet_snippet_char_cap,
    get_filenet_viewer_url_template,
    is_dev_filenet_mcp_enabled,
    is_filenet_mcp_available,
    is_filenet_mcp_flag_enabled,
)

SIDECAR_URL = "http://filenet-mcp:8811/mcp"


def _clear_env(monkeypatch):
    for var in (
        "OPENRAG_FILENET_MCP_ENABLED",
        "OPENRAG_DEV_FILENET_MCP",
        "OPENRAG_FILENET_MCP_URL",
        "OPENRAG_FILENET_MCP_TOKEN",
        "OPENRAG_FILENET_VIEWER_URL_TEMPLATE",
        "OPENRAG_FILENET_SNIPPET_CHAR_CAP",
        "OPENRAG_RUN_MODE",
    ):
        monkeypatch.delenv(var, raising=False)


def test_server_name_constant():
    assert FILENET_MCP_SERVER_NAME == "filenet-p8"


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE", " true "])
def test_kill_switch_truthy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", flag)
    assert is_filenet_mcp_flag_enabled() is True


@pytest.mark.parametrize("flag", ["false", "0", "no", "off", "", "banana"])
def test_kill_switch_falsy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", flag)
    assert is_filenet_mcp_flag_enabled() is False


def test_kill_switch_defaults_true(monkeypatch):
    _clear_env(monkeypatch)
    assert is_filenet_mcp_flag_enabled() is True


def test_dev_bypass_defaults_false(monkeypatch):
    _clear_env(monkeypatch)
    assert is_dev_filenet_mcp_enabled() is False


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on"])
def test_dev_bypass_truthy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_DEV_FILENET_MCP", flag)
    assert is_dev_filenet_mcp_enabled() is True


def test_url_default_empty_and_stripped(monkeypatch):
    _clear_env(monkeypatch)
    assert get_filenet_mcp_url() == ""
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", f"  {SIDECAR_URL}  ")
    assert get_filenet_mcp_url() == SIDECAR_URL


def test_token_default_empty_and_stripped(monkeypatch):
    _clear_env(monkeypatch)
    assert get_filenet_mcp_token() == ""
    monkeypatch.setenv("OPENRAG_FILENET_MCP_TOKEN", " s3cret ")
    assert get_filenet_mcp_token() == "s3cret"


@pytest.mark.parametrize(
    ("run_mode", "kill_switch", "dev_flag", "url", "expected"),
    [
        # Fully configured on_prem: available.
        ("on_prem", "true", "false", SIDECAR_URL, True),
        # Kill switch off always wins.
        ("on_prem", "false", "false", SIDECAR_URL, False),
        ("on_prem", "false", "true", SIDECAR_URL, False),
        # Missing URL means unavailable everywhere.
        ("on_prem", "true", "false", "", False),
        ("oss", "true", "true", "", False),
        # OSS/saas without the dev bypass: unavailable.
        ("oss", "true", "false", SIDECAR_URL, False),
        ("saas", "true", "false", SIDECAR_URL, False),
        # Dev bypass opens OSS (and saas) for local testing.
        ("oss", "true", "true", SIDECAR_URL, True),
        ("saas", "true", "true", SIDECAR_URL, True),
        # Unset/invalid run mode falls back to oss: dev bypass required.
        ("", "true", "false", SIDECAR_URL, False),
        ("", "true", "true", SIDECAR_URL, True),
    ],
)
def test_availability_truth_table(monkeypatch, run_mode, kill_switch, dev_flag, url, expected):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_ENABLED", kill_switch)
    monkeypatch.setenv("OPENRAG_DEV_FILENET_MCP", dev_flag)
    monkeypatch.setenv("OPENRAG_FILENET_MCP_URL", url)
    assert is_filenet_mcp_available() is expected


def test_availability_defaults_off(monkeypatch):
    """A pristine environment (no FileNet vars at all) leaves the tool off."""
    _clear_env(monkeypatch)
    assert is_filenet_mcp_available() is False


# ---------------------------------------------------------------------------
# Deployment-config knobs delivered to the flow as Langflow global variables
# ---------------------------------------------------------------------------

ICN_TEMPLATE = (
    "https://cpd.example.com/icn/navigator/bookmark.jsp"
    "?docid={class}%2C%7BB9F063B1-E6F4-46DD-BEF4-D5E57EDCA08F%7D%2C{id_braced}"
    "&mimeType={mimetype}&template_name={class}"
)


def test_viewer_url_template_defaults_empty(monkeypatch):
    """Unset means results carry no source link — the pre-existing behaviour."""
    _clear_env(monkeypatch)
    assert get_filenet_viewer_url_template() == ""


def test_viewer_url_template_is_stripped(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENRAG_FILENET_VIEWER_URL_TEMPLATE", f"  {ICN_TEMPLATE}  ")
    assert get_filenet_viewer_url_template() == ICN_TEMPLATE


def test_snippet_char_cap_defaults_empty(monkeypatch):
    """Unset lets the flow component apply its own 2000-char default."""
    _clear_env(monkeypatch)
    assert get_filenet_snippet_char_cap() == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20000", "20000"),
        ("  20000  ", "20000"),
        ("1", "1"),
        # Rejected here so a malformed value never reaches the flow.
        ("0", ""),
        ("-5", ""),
        ("2000.5", ""),
        ("lots", ""),
        ("", ""),
    ],
)
def test_snippet_char_cap_only_accepts_positive_integers(monkeypatch, raw, expected):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OPENRAG_FILENET_SNIPPET_CHAR_CAP", raw)
    assert get_filenet_snippet_char_cap() == expected
