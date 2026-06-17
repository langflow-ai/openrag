"""resolve_jwt_claims: verify vs decode-only modes."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import auth.ibm_auth as ibm_auth  # noqa: E402
import config.utils as config_utils  # noqa: E402


@pytest.mark.parametrize("token", [None, "", "   "])
def test_resolve_empty_token_returns_none(token):
    assert config_utils.resolve_jwt_claims(token) is None


def test_resolve_verify_mode_calls_verify_jwt_from_issuer(monkeypatch):
    monkeypatch.setenv("OPENRAG_JWT_VERIFY_SIGNATURE", "true")
    verify = MagicMock(return_value={"sub": "alice"})
    monkeypatch.setattr(config_utils, "verify_jwt_from_issuer", verify)
    decode = MagicMock()
    monkeypatch.setattr(ibm_auth, "decode_ibm_jwt", decode)

    result = config_utils.resolve_jwt_claims("Bearer tok")

    assert result == {"sub": "alice"}
    verify.assert_called_once()
    decode.assert_not_called()


def test_resolve_decode_mode_calls_decode_ibm_jwt(monkeypatch):
    monkeypatch.delenv("OPENRAG_JWT_VERIFY_SIGNATURE", raising=False)
    verify = MagicMock()
    monkeypatch.setattr(config_utils, "verify_jwt_from_issuer", verify)
    decode = MagicMock(return_value={"sub": "bob"})
    monkeypatch.setattr(ibm_auth, "decode_ibm_jwt", decode)

    result = config_utils.resolve_jwt_claims("tok")

    assert result == {"sub": "bob"}
    verify.assert_not_called()
    decode.assert_called_once_with("tok")
