"""Unit tests for the admin-managed connector enable/disable toggle.

Covers the helpers and endpoints added for ``connectors:manage:global``:
- ``is_connector_enabled`` default-enabled semantics
- ``assert_connector_enabled`` gating (kill switch, admin bypass, 403)
- ``set_connector_enabled`` persistence + authz validation
- ``list_connectors`` enabled-flag merge and non-admin hiding
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _session_returning(value):
    """A DB-session mock whose ``get`` resolves to a WorkspaceConfig-like row."""
    session = MagicMock()
    if value is None:
        session.get = AsyncMock(return_value=None)
    else:
        row = MagicMock()
        row.value = value
        session.get = AsyncMock(return_value=row)
    return session


def _connector_service(types=("google_drive", "sharepoint", "onedrive")):
    svc = MagicMock()
    cm = MagicMock()
    cm.get_available_connector_types = MagicMock(
        return_value={t: {"name": t, "description": "", "icon": t} for t in types}
    )
    svc.connection_manager = cm
    return svc


def test_is_connector_enabled_defaults_to_enabled():
    from api.connectors import is_connector_enabled

    assert is_connector_enabled({}, "google_drive") is True
    assert is_connector_enabled({"google_drive": False}, "google_drive") is False
    assert is_connector_enabled({"sharepoint": False}, "google_drive") is True


@pytest.mark.asyncio
async def test_assert_connector_enabled_bypasses_when_rbac_off(monkeypatch):
    import api.connectors as connectors

    monkeypatch.setattr(connectors, "is_rbac_enforced", lambda: False)
    # session.get would explode if reached — it must not be reached.
    session = MagicMock()
    session.get = AsyncMock(side_effect=AssertionError("should not query DB"))
    await connectors.assert_connector_enabled("google_drive", MagicMock(), MagicMock(), session)


@pytest.mark.asyncio
async def test_assert_connector_enabled_blocks_non_admin(monkeypatch):
    import api.connectors as connectors

    monkeypatch.setattr(connectors, "is_rbac_enforced", lambda: True)
    session = _session_returning({"google_drive": False})
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=False)
    user = MagicMock()
    user.db_user_id = "u1"

    with pytest.raises(HTTPException) as exc:
        await connectors.assert_connector_enabled("google_drive", user, rbac, session)
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "connector_disabled"


@pytest.mark.asyncio
async def test_assert_connector_enabled_allows_admin(monkeypatch):
    import api.connectors as connectors

    monkeypatch.setattr(connectors, "is_rbac_enforced", lambda: True)
    session = _session_returning({"google_drive": False})
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)
    user = MagicMock()
    user.db_user_id = "admin"

    # Disabled connector, but admin → no raise.
    await connectors.assert_connector_enabled("google_drive", user, rbac, session)


@pytest.mark.asyncio
async def test_set_connector_enabled_persists(monkeypatch):
    import api.connectors as connectors

    svc = _connector_service()
    session = _session_returning(None)  # no existing row
    session.commit = AsyncMock()

    captured = {}

    async def fake_upsert(self, section, value, actor_user_id=None):
        captured["section"] = section
        captured["value"] = value
        captured["actor"] = actor_user_id

    monkeypatch.setattr(connectors.WorkspaceConfigRepo, "upsert", fake_upsert)

    user = MagicMock()
    user.db_user_id = "admin"
    body = connectors.SetConnectorEnabledBody(enabled=False)

    resp = await connectors.set_connector_enabled(
        connector_type="sharepoint",
        body=body,
        connector_service=svc,
        session=session,
        user=user,
    )

    data = json.loads(resp.body.decode())
    assert data == {"connector_type": "sharepoint", "enabled": False}
    assert captured["section"] == "connectors"
    assert captured["value"] == {"sharepoint": False}
    assert captured["actor"] == "admin"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_connector_enabled_rejects_unknown_type():
    import api.connectors as connectors

    svc = _connector_service()
    session = _session_returning(None)
    user = MagicMock()
    body = connectors.SetConnectorEnabledBody(enabled=True)

    with pytest.raises(HTTPException) as exc:
        await connectors.set_connector_enabled(
            connector_type="not_a_connector",
            body=body,
            connector_service=svc,
            session=session,
            user=user,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_connectors_hides_disabled_for_non_admin(monkeypatch):
    import api.connectors as connectors

    svc = _connector_service()
    # get_available_connector_types is called with user_id=... in the handler.
    svc.connection_manager.get_available_connector_types = MagicMock(
        return_value={
            "google_drive": {"name": "g", "description": "", "icon": "g", "available": True},
            "sharepoint": {"name": "s", "description": "", "icon": "s", "available": True},
        }
    )
    session = _session_returning({"sharepoint": False})
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=False)  # non-admin
    user = MagicMock()
    user.user_id = "u1"
    user.db_user_id = "u1"

    resp = await connectors.list_connectors(
        connector_service=svc, user=user, session=session, rbac=rbac
    )
    data = json.loads(resp.body.decode())["connectors"]
    assert "google_drive" in data
    assert data["google_drive"]["enabled"] is True
    assert "sharepoint" not in data  # hidden for non-admin


@pytest.mark.asyncio
async def test_list_connectors_shows_disabled_with_flag_for_admin(monkeypatch):
    import api.connectors as connectors

    svc = _connector_service()
    svc.connection_manager.get_available_connector_types = MagicMock(
        return_value={
            "google_drive": {"name": "g", "description": "", "icon": "g", "available": True},
            "sharepoint": {"name": "s", "description": "", "icon": "s", "available": True},
        }
    )
    session = _session_returning({"sharepoint": False})
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)  # admin
    user = MagicMock()
    user.user_id = "admin"
    user.db_user_id = "admin"

    resp = await connectors.list_connectors(
        connector_service=svc, user=user, session=session, rbac=rbac
    )
    data = json.loads(resp.body.decode())["connectors"]
    assert data["google_drive"]["enabled"] is True
    assert "sharepoint" in data  # visible to admin
    assert data["sharepoint"]["enabled"] is False
