"""Change-detection strategy is a connector capability, not a hardcoded list.

``_connector_uses_timestamp_change_detection`` reads ``CHANGE_DETECTION`` from
the registered connector class, and ``is_bucket_connector_type`` derives from
``CONNECTOR_KIND`` — neither consults a type-string set anymore.
"""

import pytest

from api.connectors import _connector_uses_timestamp_change_detection
from connectors.aws_s3 import S3Connector
from connectors.base import BaseConnector
from services.connector_access_service import is_bucket_connector_type


def test_base_default_is_replace_always():
    assert BaseConnector.CHANGE_DETECTION == "replace_always"


def test_s3_declares_timestamp_change_detection():
    assert S3Connector.CHANGE_DETECTION == "timestamp"
    assert _connector_uses_timestamp_change_detection("aws_s3") is True


@pytest.mark.parametrize("connector_type", ["google_drive", "sharepoint", "onedrive"])
def test_oauth_connectors_use_replace_always(connector_type):
    assert _connector_uses_timestamp_change_detection(connector_type) is False


def test_unknown_type_defaults_to_replace_always():
    assert _connector_uses_timestamp_change_detection("no_such_connector") is False


def test_capability_read_from_registered_class(monkeypatch):
    class TimestampConnector:
        CONNECTOR_TYPE = "custom_ts"
        CHANGE_DETECTION = "timestamp"

    monkeypatch.setattr(
        "connectors.registry.get_connector_class",
        lambda connector_type: TimestampConnector if connector_type == "custom_ts" else None,
    )
    assert _connector_uses_timestamp_change_detection("custom_ts") is True


def test_is_bucket_connector_type_derived_from_kind():
    assert is_bucket_connector_type("aws_s3") is True
    assert is_bucket_connector_type("google_drive") is False
    assert is_bucket_connector_type("no_such_connector") is False
