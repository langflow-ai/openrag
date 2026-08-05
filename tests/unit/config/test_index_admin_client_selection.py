import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_saas_uses_service_token(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    sentinel = object()
    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: True)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: False)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: "svc-jwt-token")
    captured = {}

    def fake_from_jwt(token):
        captured["token"] = token
        return sentinel

    monkeypatch.setattr(settings.clients, "create_opensearch_client_from_jwt", fake_from_jwt)

    client = settings.clients.create_index_admin_opensearch_client("Bearer user-jwt")

    assert client is sentinel
    assert captured["token"] == "svc-jwt-token"


def test_saas_without_service_token_raises(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: True)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: False)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: None)

    with pytest.raises(RuntimeError, match="OPENRAG_SERVICE_TOKEN"):
        settings.clients.create_index_admin_opensearch_client("Bearer user-jwt")


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

    client = settings.clients.create_index_admin_opensearch_client(None)

    assert client is sentinel
    assert captured["token"] == "svc-jwt-token"


def test_on_prem_without_service_token_raises(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: True)
    monkeypatch.setattr(settings, "get_openrag_service_token", lambda: None)

    with pytest.raises(RuntimeError, match="OPENRAG_SERVICE_TOKEN"):
        settings.clients.create_index_admin_opensearch_client("Bearer user-jwt")


def test_oss_uses_basic_auth(monkeypatch):
    from config import settings
    from utils import run_mode_utils

    sentinel = object()
    monkeypatch.setattr(run_mode_utils, "is_run_mode_saas", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_on_prem", lambda: False)
    monkeypatch.setattr(run_mode_utils, "is_run_mode_oss", lambda: True)
    monkeypatch.setattr(settings, "get_opensearch_username", lambda: "admin")
    monkeypatch.setattr(settings, "get_opensearch_password", lambda: "secret")

    monkeypatch.setattr(settings.clients, "create_basic_opensearch_client", lambda u, p: sentinel)

    assert settings.clients.create_index_admin_opensearch_client(None) is sentinel
