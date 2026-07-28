"""Sync replace-on-duplicate is a connector capability, not a hardcoded list.

``_connector_sync_should_replace`` reads ``SYNC_REPLACES_DUPLICATES`` from the
connector class registered for the type. The BaseConnector default is True so
a new connector gets change-propagating sync without touching the API module.
"""

import pytest

from api.connectors import _connector_sync_should_replace
from connectors.base import BaseConnector


@pytest.mark.parametrize("connector_type", ["google_drive", "sharepoint", "onedrive"])
def test_builtin_oauth_connectors_replace_on_sync(connector_type):
    assert _connector_sync_should_replace(connector_type) is True


def test_unknown_connector_type_does_not_replace():
    assert _connector_sync_should_replace("no_such_connector") is False


def test_new_connector_inherits_replace_default():
    class NewConnector(BaseConnector):
        CONNECTOR_TYPE = "new_connector"

        async def authenticate(self):  # pragma: no cover - capability test only
            return True

        async def setup_subscription(self):  # pragma: no cover
            raise NotImplementedError

        async def list_files(self, page_token=None, max_files=None, **kwargs):  # pragma: no cover
            raise NotImplementedError

        async def get_file_content(self, file_id):  # pragma: no cover
            raise NotImplementedError

        async def handle_webhook(self, payload):  # pragma: no cover
            raise NotImplementedError

        async def cleanup_subscription(self, subscription_id):  # pragma: no cover
            raise NotImplementedError

    assert NewConnector.SYNC_REPLACES_DUPLICATES is True


def test_connector_can_opt_out_via_attribute(monkeypatch):
    class OptOutConnector:
        CONNECTOR_TYPE = "opt_out"
        SYNC_REPLACES_DUPLICATES = False

    monkeypatch.setattr(
        "connectors.registry.get_connector_class",
        lambda connector_type: OptOutConnector if connector_type == "opt_out" else None,
    )
    assert _connector_sync_should_replace("opt_out") is False
