"""Connector failure logs keep their diagnostic, except for customer plugins.

HTTP responses never echo exception text. Logs do for built-in and enhancement
connectors, which is the operator's only clue to an OAuth/listing/bucket
failure; a plugin's message may carry source detail (internal URLs, account
names), so only its exception type is logged (review 1h).
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api import connectors as connectors_api  # noqa: E402
from session_manager import User  # noqa: E402

SECRET_DETAIL = "https://intranet.example/sites/hr as CORP\\svc-reader"


class _FakeRequest:
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}


@pytest.fixture
def plugin_type(monkeypatch):
    monkeypatch.setattr(connectors_api, "is_plugin_connector_type", lambda value: value == "acme")
    return "acme"


@pytest.fixture
def logged(monkeypatch):
    records: list[tuple[str, str, dict]] = []
    for level in ("error", "warning"):
        monkeypatch.setattr(
            connectors_api.logger,
            level,
            lambda msg, _level=level, **kw: records.append((_level, msg, kw)),
        )
    return records


def test_builtin_connector_failure_logs_message_and_type(plugin_type):
    fields = connectors_api._connector_error_log_fields(
        "google_drive", RuntimeError("invalid_grant: token revoked")
    )
    assert fields == {"error_type": "RuntimeError", "error": "invalid_grant: token revoked"}


def test_plugin_connector_failure_logs_only_the_type(plugin_type):
    fields = connectors_api._connector_error_log_fields(plugin_type, ValueError(SECRET_DETAIL))
    assert fields == {"error_type": "ValueError"}


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_type", ["google_drive", "acme"])
async def test_state_map_failure_log(connector_type, plugin_type, logged):
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.side_effect = RuntimeError(SECRET_DETAIL)

    assert (
        await connectors_api.get_synced_file_state_map(connector_type, "u1", session_manager) == {}
    )

    ((_, message, fields),) = [
        r for r in logged if r[1] == "Failed to build connector file state map"
    ]
    assert fields["error_type"] == "RuntimeError"
    assert ("error" in fields) is (connector_type != plugin_type)
    if connector_type == plugin_type:
        assert SECRET_DETAIL not in repr(fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_type", ["google_drive", "acme"])
async def test_status_auth_failure_log_and_response(connector_type, plugin_type, logged):
    from sqlalchemy.ext.asyncio import AsyncSession

    connection = MagicMock()
    connection.connection_id = "conn-1"
    connection.connector_type = connector_type
    connection.user_id = "alice"
    connection.is_active = True
    connection.name = "Source"
    connection.created_at = datetime.now()
    connection.last_sync = None
    connector = MagicMock()
    connector.authenticate = AsyncMock(side_effect=RuntimeError(SECRET_DETAIL))
    service = MagicMock()
    service._get_connector = AsyncMock(return_value=connector)
    service.connection_manager.list_connections = AsyncMock(return_value=[connection])
    service.connection_manager.has_env_credentials.return_value = False

    response = await connectors_api.connector_status(
        connector_type,
        _FakeRequest(),
        connector_service=service,
        user=User(user_id="alice", name="Alice", email="alice@example.com"),
        session=MagicMock(spec=AsyncSession),
    )

    assert SECRET_DETAIL not in response.body.decode()
    ((_, _, fields),) = [r for r in logged if r[1] == "Could not verify connector authentication"]
    assert fields["connector_type"] == connector_type
    assert fields["error_type"] == "RuntimeError"
    if connector_type == plugin_type:
        assert "error" not in fields
    else:
        assert fields["error"] == SECRET_DETAIL
