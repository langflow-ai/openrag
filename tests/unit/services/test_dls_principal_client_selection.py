import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_service():
    from services.dls_principal_service import DLSPrincipalService

    # connector_service is unused by _get_opensearch_client; ttl=0 avoids the
    # DLS_PRINCIPAL_REFRESH_TTL_SECONDS import path.
    return DLSPrincipalService(connector_service=object(), refresh_ttl_seconds=0)


def test_injected_client_wins():
    sentinel = object()
    from services.dls_principal_service import DLSPrincipalService

    service = DLSPrincipalService(
        connector_service=object(),
        opensearch_client=sentinel,
        refresh_ttl_seconds=0,
    )
    assert service._get_opensearch_client() is sentinel


def test_saas_uses_service_token(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    sentinel = object()
    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: True)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: "svc-jwt-token")
    captured = {}

    def fake_from_jwt(token):
        captured["token"] = token
        return sentinel

    monkeypatch.setattr(settings.clients, "create_opensearch_client_from_jwt", fake_from_jwt)

    service = _make_service()
    client = service._get_opensearch_client()

    assert client is sentinel
    assert captured["token"] == "svc-jwt-token"
    # Built once and cached for subsequent calls.
    assert service._get_opensearch_client() is sentinel


def test_saas_without_service_token_raises(monkeypatch):
    import pytest

    from config import settings
    from utils import run_mode_utils

    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: True)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: None)

    service = _make_service()
    with pytest.raises(RuntimeError):
        service._get_opensearch_client()


def test_on_prem_uses_service_token(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    sentinel = object()
    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: True)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: "svc-jwt-token")
    captured = {}

    def fake_from_jwt(token):
        captured["token"] = token
        return sentinel

    monkeypatch.setattr(settings.clients, "create_opensearch_client_from_jwt", fake_from_jwt)

    service = _make_service()
    client = service._get_opensearch_client()

    assert client is sentinel
    assert captured["token"] == "svc-jwt-token"


def test_on_prem_without_service_token_raises(monkeypatch):
    import pytest

    from config import settings
    from utils import run_mode_utils

    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: True)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: None)

    service = _make_service()
    with pytest.raises(RuntimeError):
        service._get_opensearch_client()


def test_oss_uses_basic_auth(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    sentinel = object()
    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: False)
    monkeypatch.setattr(settings, "get_opensearch_username", lambda: "admin")
    monkeypatch.setattr(settings, "get_opensearch_password", lambda: "secret")
    captured = {}

    def fake_basic(username, password):
        captured["creds"] = (username, password)
        return sentinel

    monkeypatch.setattr(settings.clients, "create_basic_opensearch_client", fake_basic)

    service = _make_service()
    client = service._get_opensearch_client()

    assert client is sentinel
    assert captured["creds"] == ("admin", "secret")


def test_oss_without_password_returns_none(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: False)
    monkeypatch.setattr(settings, "get_opensearch_username", lambda: "admin")
    monkeypatch.setattr(settings, "get_opensearch_password", lambda: None)

    service = _make_service()
    assert service._get_opensearch_client() is None
