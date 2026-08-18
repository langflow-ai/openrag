"""Unit tests asserting that status routes are registered only in OSS run mode.

Route registration reads OPENRAG_RUN_MODE (via is_run_mode_oss()) at the
moment register_*_routes() is called.  Because each route module imports
is_run_mode_oss by name at module load time, we must patch the name inside
each route module — not the originating utils module.
"""

import sys
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import app.routes.internal as internal_routes  # noqa: E402
import app.routes.public_v1 as public_v1_routes  # noqa: E402
from app.routes.internal import register_internal_routes  # noqa: E402
from app.routes.public_v1 import register_public_v1_routes  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_paths(app: FastAPI) -> set[str]:
    """Return the set of URL path strings registered on the app."""
    return {route.path for route in app.routes if hasattr(route, "path")}


def _matching_routes(app: FastAPI, path: str, method: str) -> list:
    """Return every registered route matching *path* and *method* (no dedup).

    Unlike _route_paths (a set), this preserves duplicate registrations so
    tests can assert exactly one route exists for a given path/method.
    """
    return [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and method.upper() in getattr(route, "methods", set())
    ]


def _make_app_public(monkeypatch, *, oss: bool) -> FastAPI:
    monkeypatch.setattr(public_v1_routes, "is_run_mode_oss", lambda: oss)
    app = FastAPI()
    register_public_v1_routes(app)
    return app


def _make_app_internal(monkeypatch, *, oss: bool) -> FastAPI:
    monkeypatch.setattr(internal_routes, "is_run_mode_oss", lambda: oss)
    app = FastAPI()
    register_internal_routes(app)
    return app


# ---------------------------------------------------------------------------
# Public /v1/status routes
# ---------------------------------------------------------------------------


class TestPublicStatusRoutesOss:
    def test_v1_status_registered(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=True)
        assert "/v1/status" in _route_paths(app)

    def test_v1_status_logs_registered(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=True)
        assert "/v1/status/{component}/logs" in _route_paths(app)


class TestPublicStatusRoutesSaas:
    def test_v1_status_absent(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/status" not in _route_paths(app)

    def test_v1_status_logs_absent(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/status/{component}/logs" not in _route_paths(app)


class TestPublicStatusRoutesOnPrem:
    """on_prem is not OSS — routes must be absent."""

    def test_v1_status_absent(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/status" not in _route_paths(app)

    def test_v1_status_logs_absent(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/status/{component}/logs" not in _route_paths(app)


# ---------------------------------------------------------------------------
# Internal /api/status route
# ---------------------------------------------------------------------------


class TestInternalStatusRouteOss:
    def test_status_registered(self, monkeypatch):
        app = _make_app_internal(monkeypatch, oss=True)
        assert "/status" in _route_paths(app)


class TestInternalStatusRouteSaas:
    def test_status_absent(self, monkeypatch):
        app = _make_app_internal(monkeypatch, oss=False)
        assert "/status" not in _route_paths(app)


class TestInternalStatusRouteOnPrem:
    def test_status_absent(self, monkeypatch):
        app = _make_app_internal(monkeypatch, oss=False)
        assert "/status" not in _route_paths(app)


# ---------------------------------------------------------------------------
# OSS unset (env default) — is_run_mode_oss() treats unset as "oss"
# ---------------------------------------------------------------------------


class TestPublicStatusDefaultEnv:
    def test_v1_status_present_when_env_unset(self, monkeypatch):
        """OPENRAG_RUN_MODE unset defaults to oss — routes must be registered."""
        from utils import run_mode_utils

        monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)
        # Restore the real function so we exercise get_run_mode()'s default logic.
        monkeypatch.setattr(
            public_v1_routes,
            "is_run_mode_oss",
            run_mode_utils.is_run_mode_oss,
        )
        app = FastAPI()
        register_public_v1_routes(app)
        assert "/v1/status" in _route_paths(app)
        assert "/v1/status/{component}/logs" in _route_paths(app)


# ---------------------------------------------------------------------------
# Non-status routes are always registered regardless of run mode
# ---------------------------------------------------------------------------


class TestNonStatusRoutesUnaffected:
    def test_chat_route_present_in_saas(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/chat" in _route_paths(app)

    def test_search_route_present_in_saas(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=False)
        assert "/v1/search" in _route_paths(app)

    def test_health_route_present_in_saas(self, monkeypatch):
        app = _make_app_internal(monkeypatch, oss=False)
        assert "/health" in _route_paths(app)

    def test_chat_route_present_in_oss(self, monkeypatch):
        app = _make_app_public(monkeypatch, oss=True)
        assert "/v1/chat" in _route_paths(app)
