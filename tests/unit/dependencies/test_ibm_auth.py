import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dependencies import _get_ibm_user  # noqa: E402


@pytest.mark.asyncio
async def test_ibm_header_auth_uses_opensearch_username_without_session_cookie(monkeypatch):
    monkeypatch.setattr("config.settings.IBM_CREDENTIALS_HEADER", "X-Test-IBM-Credentials")
    monkeypatch.setattr("config.settings.IBM_SESSION_COOKIE_NAME", "ibm-openrag-session")
    monkeypatch.setattr("config.settings.PLATFORM_USERNAME", "")
    monkeypatch.setattr("config.settings.PLATFORM_PASSWORD", "")

    class ConnectionManager:
        def __init__(self):
            self.upserts = []

        async def upsert_ibm_credentials(self, **kwargs):
            self.upserts.append(kwargs)

    connection_manager = ConnectionManager()
    request = SimpleNamespace(
        headers={
            "X-Test-IBM-Credentials": "Basic "
            + base64.b64encode(b"ibmlhapikey_user-1:secret").decode()
        },
        cookies={},
        state=SimpleNamespace(),
        app=SimpleNamespace(
            state=SimpleNamespace(
                services={
                    "connector_service": SimpleNamespace(connection_manager=connection_manager)
                }
            )
        ),
    )

    user = await _get_ibm_user(request, required=True)

    assert user.user_id == "ibmlhapikey_user-1"
    assert user.email == "ibmlhapikey_user-1"
    assert user.name == "ibmlhapikey_user-1"
    assert user.opensearch_username == "ibmlhapikey_user-1"
    assert request.state.user == user
    assert connection_manager.upserts == [
        {
            "user_id": "ibmlhapikey_user-1",
            "basic_credentials": request.headers["X-Test-IBM-Credentials"],
            "username": "ibmlhapikey_user-1",
        }
    ]
