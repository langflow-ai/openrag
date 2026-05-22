"""Unit tests for the JWT claims LRU+TTL cache in session_manager and ibm_auth.

Verifies cache hit/miss behaviour, stale-entry eviction, and that decode
failures are never cached. Each test clears the module-level caches in a
fixture so tests are fully isolated.
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Patch heavy config imports before importing session_manager
import os

os.environ.setdefault("OPENRAG_JWT_CACHE_TTL", "60")
os.environ.setdefault("OPENRAG_JWT_CACHE_MAXSIZE", "1024")

import auth.ibm_auth as ibm_auth  # noqa: E402
import session_manager as sm  # noqa: E402
from auth.ibm_auth import _IBM_JWT_CLAIMS_CACHE  # noqa: E402
from session_manager import _JWT_CLAIMS_CACHE  # noqa: E402

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_caches():
    """Ensure every test starts with empty caches."""
    _JWT_CLAIMS_CACHE.clear()
    _IBM_JWT_CLAIMS_CACHE.clear()
    yield
    _JWT_CLAIMS_CACHE.clear()
    _IBM_JWT_CLAIMS_CACHE.clear()


def _make_session_manager(public_key=None, algorithm="RS256"):
    """Return a minimal SessionManager with a mock public key."""
    mgr = sm.SessionManager.__new__(sm.SessionManager)
    mgr.public_key = public_key or MagicMock()
    mgr.algorithm = algorithm
    return mgr


# ─── session_manager.verify_token ────────────────────────────────────────────


class TestVerifyTokenCache:
    TOKEN = "eyJhbGciOiJSUzI1NiJ9.payload.sig"
    CLAIMS = {"sub": "u1", "exp": int(time.time()) + 3600, "user_id": "u1"}

    def test_cache_hit_skips_decode(self):
        mgr = _make_session_manager()
        with patch("session_manager.jwt.decode", return_value=self.CLAIMS) as mock_decode:
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                result1 = mgr.verify_token(f"Bearer {self.TOKEN}")
                result2 = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert result1 == self.CLAIMS
        assert result2 == self.CLAIMS
        mock_decode.assert_called_once()  # second call served from cache

    def test_cache_miss_calls_decode(self):
        mgr = _make_session_manager()
        with patch("session_manager.jwt.decode", return_value=self.CLAIMS) as mock_decode:
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                result = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert result == self.CLAIMS
        mock_decode.assert_called_once()
        assert self.TOKEN in _JWT_CLAIMS_CACHE

    def test_stale_exp_evicts_and_returns_none(self):
        stale = {"sub": "u1", "exp": int(time.time()) - 1, "user_id": "u1"}
        _JWT_CLAIMS_CACHE[self.TOKEN] = stale

        mgr = _make_session_manager()
        with patch("session_manager.jwt.decode", side_effect=sm.jwt.ExpiredSignatureError):
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                result = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert result is None
        assert self.TOKEN not in _JWT_CLAIMS_CACHE  # evicted by exp recheck

    def test_expired_signature_error_not_cached(self):
        mgr = _make_session_manager()
        with patch(
            "session_manager.jwt.decode", side_effect=sm.jwt.ExpiredSignatureError
        ) as mock_decode:
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                r1 = mgr.verify_token(f"Bearer {self.TOKEN}")
                r2 = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert r1 is None
        assert r2 is None
        assert mock_decode.call_count == 2  # not cached — decode called both times
        assert self.TOKEN not in _JWT_CLAIMS_CACHE

    def test_invalid_token_error_not_cached(self):
        mgr = _make_session_manager()
        with patch(
            "session_manager.jwt.decode", side_effect=sm.jwt.InvalidTokenError
        ) as mock_decode:
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                r1 = mgr.verify_token(f"Bearer {self.TOKEN}")
                r2 = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert r1 is None
        assert r2 is None
        assert mock_decode.call_count == 2

    def test_bearer_prefix_stripped_for_cache_key(self):
        mgr = _make_session_manager()
        with patch("session_manager.jwt.decode", return_value=self.CLAIMS):
            with patch("session_manager.IBM_AUTH_ENABLED", False):
                mgr.verify_token(f"Bearer {self.TOKEN}")

        assert self.TOKEN in _JWT_CLAIMS_CACHE
        assert f"Bearer {self.TOKEN}" not in _JWT_CLAIMS_CACHE

    def test_ibm_auth_enabled_bypasses_cache(self):
        mgr = _make_session_manager()
        with patch("session_manager.jwt.decode") as mock_decode:
            with patch("session_manager.IBM_AUTH_ENABLED", True):
                result = mgr.verify_token(f"Bearer {self.TOKEN}")

        assert result is None
        mock_decode.assert_not_called()
        assert len(_JWT_CLAIMS_CACHE) == 0


# ─── auth.ibm_auth.decode_ibm_jwt ────────────────────────────────────────────


class TestDecodeIbmJwtCache:
    TOKEN = "ibm.token.value"
    CLAIMS = {"sub": "ibm-u1", "exp": int(time.time()) + 3600}

    def test_cache_hit_skips_decode(self):
        with patch("auth.ibm_auth.jwt.decode", return_value=self.CLAIMS) as mock_decode:
            r1 = ibm_auth.decode_ibm_jwt(self.TOKEN)
            r2 = ibm_auth.decode_ibm_jwt(self.TOKEN)

        assert r1 == self.CLAIMS
        assert r2 == self.CLAIMS
        mock_decode.assert_called_once()

    def test_cache_miss_calls_decode(self):
        with patch("auth.ibm_auth.jwt.decode", return_value=self.CLAIMS) as mock_decode:
            result = ibm_auth.decode_ibm_jwt(self.TOKEN)

        assert result == self.CLAIMS
        mock_decode.assert_called_once()
        assert self.TOKEN in _IBM_JWT_CLAIMS_CACHE

    def test_stale_exp_evicts_and_redecodes(self):
        stale = {"sub": "ibm-u1", "exp": int(time.time()) - 1}
        _IBM_JWT_CLAIMS_CACHE[self.TOKEN] = stale

        fresh = {"sub": "ibm-u1", "exp": int(time.time()) + 3600}
        with patch("auth.ibm_auth.jwt.decode", return_value=fresh) as mock_decode:
            result = ibm_auth.decode_ibm_jwt(self.TOKEN)

        assert result == fresh
        mock_decode.assert_called_once()  # re-decoded after stale eviction
        assert _IBM_JWT_CLAIMS_CACHE[self.TOKEN] == fresh

    def test_invalid_token_not_cached(self):
        import jwt as pyjwt

        with patch("auth.ibm_auth.jwt.decode", side_effect=pyjwt.InvalidTokenError) as mock_decode:
            r1 = ibm_auth.decode_ibm_jwt(self.TOKEN)
            r2 = ibm_auth.decode_ibm_jwt(self.TOKEN)

        assert r1 is None
        assert r2 is None
        assert mock_decode.call_count == 2
        assert self.TOKEN not in _IBM_JWT_CLAIMS_CACHE
