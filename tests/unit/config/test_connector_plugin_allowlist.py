"""OPENRAG_CONNECTOR_PLUGINS is parsed in config.settings, at call time."""

import pytest

from config.settings import get_connector_plugin_allowlist


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", frozenset()),
        ("  ,  , ", frozenset()),
        ("sharepoint_onprem", frozenset({"sharepoint_onprem"})),
        (" sharepoint_onprem , acme,acme ", frozenset({"sharepoint_onprem", "acme"})),
    ],
)
def test_allowlist_is_a_trimmed_set_of_names(monkeypatch, raw, expected):
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", raw)
    assert get_connector_plugin_allowlist() == expected


def test_unset_means_no_plugins(monkeypatch):
    monkeypatch.delenv("OPENRAG_CONNECTOR_PLUGINS", raising=False)
    assert get_connector_plugin_allowlist() == frozenset()


def test_invalid_names_pass_through_for_the_registry_to_reject(monkeypatch):
    # The registry owns validation so it can fail startup with a clear error.
    monkeypatch.setenv("OPENRAG_CONNECTOR_PLUGINS", "SharePoint")
    assert get_connector_plugin_allowlist() == frozenset({"SharePoint"})
