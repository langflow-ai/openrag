"""Tests for CORS_ALLOWED_ORIGINS parsing and middleware wiring."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"

PRINT_ORIGINS = (
    "from config.settings import CORS_ALLOWED_ORIGINS; "
    "import json; print(json.dumps(CORS_ALLOWED_ORIGINS))"
)


def _python_env(env: dict[str, str]) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(env)
    return merged


def _run_settings(extra_env: dict[str, str]) -> list[str]:
    env = _python_env({"PYTHONPATH": str(SRC), **extra_env})
    env.pop("CORS_ALLOWED_ORIGINS", None)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", PRINT_ORIGINS],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    import json

    return json.loads(result.stdout.splitlines()[-1])


def test_parses_comma_separated_origins():
    origins = _run_settings({"CORS_ALLOWED_ORIGINS": "https://a.com,https://b.com"})
    assert origins == ["https://a.com", "https://b.com"]


def test_trims_whitespace():
    origins = _run_settings({"CORS_ALLOWED_ORIGINS": " https://a.com , https://b.com "})
    assert origins == ["https://a.com", "https://b.com"]


def test_filters_empty_entries():
    origins = _run_settings({"CORS_ALLOWED_ORIGINS": "https://a.com,,https://b.com,"})
    assert origins == ["https://a.com", "https://b.com"]


def test_empty_string_yields_empty_list():
    origins = _run_settings({"CORS_ALLOWED_ORIGINS": ""})
    assert origins == []


def test_unset_defaults_to_localhost():
    env = _python_env({"PYTHONPATH": str(SRC)})
    env.pop("CORS_ALLOWED_ORIGINS", None)
    result = subprocess.run(
        [sys.executable, "-c", PRINT_ORIGINS],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=str(ROOT),
    )
    import json

    origins = json.loads(result.stdout.splitlines()[-1])
    assert origins == ["http://localhost:3000"]


# ---------------------------------------------------------------------------
# Factory middleware wiring
# ---------------------------------------------------------------------------


def _get_cors_middleware(app):
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw
    return None


@pytest.mark.asyncio
async def test_factory_adds_cors_middleware_when_origins_set():
    with patch("app.factory.CORS_ALLOWED_ORIGINS", ["https://app.example.com"]), \
         patch("app.factory.initialize_services", new_callable=AsyncMock):
        from app.factory import create_app

        app = await create_app()
        mw = _get_cors_middleware(app)
        assert mw is not None
        assert mw.kwargs["allow_origins"] == ["https://app.example.com"]


@pytest.mark.asyncio
async def test_factory_skips_cors_middleware_when_origins_empty():
    with patch("app.factory.CORS_ALLOWED_ORIGINS", []), \
         patch("app.factory.initialize_services", new_callable=AsyncMock):
        from app.factory import create_app

        app = await create_app()
        assert _get_cors_middleware(app) is None


@pytest.mark.asyncio
async def test_factory_never_uses_wildcard_origin():
    with patch("app.factory.CORS_ALLOWED_ORIGINS", ["https://app.example.com"]), \
         patch("app.factory.initialize_services", new_callable=AsyncMock):
        from app.factory import create_app

        app = await create_app()
        mw = _get_cors_middleware(app)
        assert mw is not None
        assert "*" not in mw.kwargs["allow_origins"]
