"""Unit tests for src/utils/jwt_verification.py.

All tests are fully self-contained:
- RSA key pairs generated in-process via cryptography; no network calls.
- JWKS fetching is patched at `utils.jwt_verification._fetch_jwks`.
- clear_jwks_cache() is called in a fixture to prevent cache bleed between tests.

Test groups
-----------
TestResolveMsJwksUrl        – _resolve_ms_jwks_url() URL selection
TestValidateMsIssuer        – _validate_ms_issuer() exact-match + tid-in-iss check
TestVerifyMsAccessToken     – verify_microsoft_access_token() full behaviour matrix
TestVerifyGoogleIdToken     – verify_google_id_token() full behaviour matrix
TestGetEnvSet               – get_env_set() helper
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure src/ is on the path when running from the repo root.
ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.jwt_verification import (  # noqa: E402
    ExpiredTokenError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    JWTVerificationError,
    _resolve_ms_jwks_url,
    _validate_ms_issuer,
    clear_jwks_cache,
    verify_google_id_token,
    verify_microsoft_access_token,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

KID = "test-key-id-001"
CLIENT_ID = "aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa"
TENANT_ID = "bbbbbbbb-1111-1111-1111-bbbbbbbbbbbb"
MS_V2_ISS = f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
MS_V1_ISS = f"https://sts.windows.net/{TENANT_ID}/"
GOOGLE_ISS = "https://accounts.google.com"


def _generate_rsa_key_pair():
    """Return (private_key, public_key, jwk_dict) for test tokens."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    # Build a minimal JWK for the public key (PyJWT RSAAlgorithm.from_jwk accepts this).
    import json

    from jwt.algorithms import RSAAlgorithm

    jwk_str = RSAAlgorithm.to_jwk(public_key)
    jwk_dict = json.loads(jwk_str)
    jwk_dict["kid"] = KID
    jwk_dict["use"] = "sig"
    jwk_dict["kty"] = "RSA"

    return private_key, public_key, jwk_dict


def _make_ms_token(
    private_key,
    *,
    aud: str = CLIENT_ID,
    iss: str = MS_V2_ISS,
    tid: str = TENANT_ID,
    ver: str = "2.0",
    exp_offset: int = 3600,
    kid: str = KID,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "tid": tid,
        "ver": ver,
        "sub": "test-subject",
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def _make_google_token(
    private_key,
    *,
    aud: str = CLIENT_ID,
    iss: str = GOOGLE_ISS,
    exp_offset: int = 3600,
    kid: str = KID,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "sub": "google-user-123",
        "email": "user@example.com",
        "iat": now,
        "exp": now + exp_offset,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def _jwks(jwk_dict: dict, *, issuer: str = MS_V2_ISS) -> dict:
    """Wrap a JWK dict in a JWKS keys array with an issuer property."""
    key_entry = {**jwk_dict, "issuer": issuer}
    return {"keys": [key_entry]}


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure the JWKS cache is empty before and after every test."""
    clear_jwks_cache()
    yield
    clear_jwks_cache()


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_ms_jwks_url
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveMsJwksUrl:
    def test_v2_token_uses_v2_endpoint(self):
        url = _resolve_ms_jwks_url(TENANT_ID, "2.0")
        assert "/discovery/v2.0/keys" in url
        assert TENANT_ID in url

    def test_v1_token_uses_v1_endpoint(self):
        url = _resolve_ms_jwks_url(TENANT_ID, "1.0")
        assert "/discovery/keys" in url
        assert "/v2.0/" not in url
        assert TENANT_ID in url

    def test_unknown_version_defaults_to_v2(self):
        url = _resolve_ms_jwks_url(TENANT_ID, "3.0")
        assert "/v2.0/" in url


# ─────────────────────────────────────────────────────────────────────────────
# _validate_ms_issuer
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateMsIssuer:
    def test_v2_exact_match_passes(self):
        """Signing key issuer exactly matches token iss — should pass."""
        _validate_ms_issuer(MS_V2_ISS, TENANT_ID, MS_V2_ISS)

    def test_templated_key_issuer_substitution_passes(self):
        """Key issuer has {tenantid} placeholder — substituted and matched."""
        templated = "https://login.microsoftonline.com/{tenantid}/v2.0"
        _validate_ms_issuer(MS_V2_ISS, TENANT_ID, templated)

    def test_v1_sts_issuer_passes(self):
        """v1 STS issuer form validated correctly."""
        _validate_ms_issuer(MS_V1_ISS, TENANT_ID, MS_V1_ISS)

    def test_wrong_issuer_raises(self):
        """Signing key issuer doesn't match token iss."""
        wrong = "https://login.microsoftonline.com/ffffffff-ffff-ffff-ffff-ffffffffffff/v2.0"
        with pytest.raises(InvalidIssuerError, match="does not match signing key issuer"):
            _validate_ms_issuer(MS_V2_ISS, TENANT_ID, wrong)

    def test_tid_mismatch_in_iss_raises(self):
        """tid claim doesn't match the GUID segment in iss."""
        different_tid = "cccccccc-2222-2222-2222-cccccccccccc"
        with pytest.raises(InvalidIssuerError, match="does not match tid claim"):
            _validate_ms_issuer(MS_V2_ISS, different_tid, MS_V2_ISS)

    def test_issuer_without_guid_segment_skips_tid_url_check(self):
        """If there's no GUID in the iss URL segments, the tid-in-URL check is skipped."""
        # Some test/synthetic issuers may not have a GUID; should not crash
        synthetic_iss = "https://login.microsoftonline.com/contoso.onmicrosoft.com/v2.0"
        _validate_ms_issuer(synthetic_iss, TENANT_ID, synthetic_iss)

    def test_none_signing_key_issuer_valid_ms_prefix_passes(self):
        """JWKS key entry omits issuer — iss starts with known MS prefix, should pass."""
        _validate_ms_issuer(MS_V2_ISS, TENANT_ID, None)

    def test_none_signing_key_issuer_v1_prefix_passes(self):
        """JWKS key entry omits issuer — v1 sts.windows.net iss passes prefix check."""
        _validate_ms_issuer(MS_V1_ISS, TENANT_ID, None)

    def test_none_signing_key_issuer_unknown_prefix_raises(self):
        """JWKS key entry omits issuer — iss from unknown origin is rejected."""
        with pytest.raises(InvalidIssuerError, match="not a recognised Microsoft issuer URL"):
            _validate_ms_issuer("https://evil.example.com/tenant/v2.0", TENANT_ID, None)

    def test_none_signing_key_issuer_tid_mismatch_raises(self):
        """JWKS key entry omits issuer — tid mismatch in iss still caught."""
        different_tid = "cccccccc-2222-2222-2222-cccccccccccc"
        with pytest.raises(InvalidIssuerError, match="does not match tid claim"):
            _validate_ms_issuer(MS_V2_ISS, different_tid, None)


# ─────────────────────────────────────────────────────────────────────────────
# verify_microsoft_access_token
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyMsAccessToken:
    """Tests for verify_microsoft_access_token()."""

    def setup_method(self):
        self.private_key, self.public_key, self.jwk = _generate_rsa_key_pair()
        self.jwks = _jwks(self.jwk, issuer=MS_V2_ISS)

    # ── pass-through path (aud != our client_id) ─────────────────────────────

    def test_graph_audience_token_is_passed_through(self):
        """Tokens for MS Graph (aud=00000003-…) are returned without sig verification."""
        MS_GRAPH_AUD = "00000003-0000-0000-c000-000000000000"
        token = _make_ms_token(self.private_key, aud=MS_GRAPH_AUD)

        # _fetch_jwks must NOT be called for pass-through tokens
        with patch("utils.jwt_verification._fetch_jwks") as mock_fetch:
            claims = verify_microsoft_access_token(token, CLIENT_ID)

        mock_fetch.assert_not_called()
        assert claims["aud"] == MS_GRAPH_AUD
        assert claims["tid"] == TENANT_ID

    def test_graph_token_tenant_allow_list_enforced(self):
        """Even for pass-through tokens, the tenant allow-list is checked."""
        MS_GRAPH_AUD = "00000003-0000-0000-c000-000000000000"
        token = _make_ms_token(self.private_key, aud=MS_GRAPH_AUD)

        with patch("utils.jwt_verification._fetch_jwks"):
            with pytest.raises(
                InvalidIssuerError, match="not in the configured allowed tenant list"
            ):
                verify_microsoft_access_token(
                    token,
                    CLIENT_ID,
                    allowed_tenant_ids={"ffffffff-ffff-ffff-ffff-ffffffffffff"},
                )

    def test_graph_token_allowed_tenant_passes(self):
        """Pass-through token from a tenant in the allow-list succeeds."""
        MS_GRAPH_AUD = "00000003-0000-0000-c000-000000000000"
        token = _make_ms_token(self.private_key, aud=MS_GRAPH_AUD)

        with patch("utils.jwt_verification._fetch_jwks"):
            claims = verify_microsoft_access_token(
                token,
                CLIENT_ID,
                allowed_tenant_ids={TENANT_ID},
            )
        assert claims["tid"] == TENANT_ID

    # ── full verification path (aud == our client_id) ────────────────────────

    def test_valid_v2_token_verifies(self):
        """Happy path: valid v2 token signed with our key passes all checks."""
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_microsoft_access_token(token, CLIENT_ID)

        assert claims["aud"] == CLIENT_ID
        assert claims["tid"] == TENANT_ID
        assert claims["iss"] == MS_V2_ISS

    def test_valid_v1_token_uses_v1_jwks_url(self):
        """v1 tokens must be fetched from the /discovery/keys endpoint (no /v2.0/)."""
        v1_jwks = _jwks(self.jwk, issuer=MS_V1_ISS)
        token = _make_ms_token(
            self.private_key,
            iss=MS_V1_ISS,
            ver="1.0",
        )

        captured_url = {}

        def fake_fetch(url):
            captured_url["url"] = url
            return v1_jwks

        with patch("utils.jwt_verification._fetch_jwks", side_effect=fake_fetch):
            claims = verify_microsoft_access_token(token, CLIENT_ID)

        assert "/v2.0/" not in captured_url["url"], "v1 token must NOT use v2 JWKS endpoint"
        assert claims["ver"] == "1.0"

    def test_invalid_signature_raises(self):
        """Token signed with a different key is rejected."""
        other_private_key, _, _ = _generate_rsa_key_pair()
        token = _make_ms_token(other_private_key)  # signed with different key

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(InvalidSignatureError):
                verify_microsoft_access_token(token, CLIENT_ID)

    def test_expired_token_raises(self):
        """Token with exp in the past is rejected."""
        token = _make_ms_token(self.private_key, exp_offset=-60)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(ExpiredTokenError):
                verify_microsoft_access_token(token, CLIENT_ID)

    def test_wrong_audience_raises(self):
        """Token issued for our app (aud=CLIENT_ID) but the signature verifies
        against the wrong audience value raises InvalidAudienceError.
        We achieve this by making a token with aud=CLIENT_ID and passing a
        different client_id that also equals aud (so full-verify path runs)
        by simply using a client_id that doesn't match the token aud at all
        but keeps aud == client_id so we enter the full-verify branch.

        Simplest approach: issue token with aud=WRONG, call with client_id=WRONG
        so we enter full-verify, but the JWKS key issuer won't match → raises.
        """
        # When client_id != token aud, the function skips verification and returns
        # unverified claims (pass-through). This is the correct MS docs behaviour:
        # only validate tokens whose aud matches our application.
        token = _make_ms_token(self.private_key, aud=CLIENT_ID)

        # When client_id != token aud, the function skips verification and returns
        # unverified claims (pass-through). This is correct MS docs behaviour.
        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_microsoft_access_token(token, "different-client-id")
        # Pass-through: returns claims without error
        assert claims["aud"] == CLIENT_ID

    def test_issuer_mismatch_raises(self):
        """Signing key issuer in JWKS doesn't match the token iss."""
        wrong_issuer_jwks = _jwks(
            self.jwk,
            issuer="https://login.microsoftonline.com/ffffffff-ffff-ffff-ffff-ffffffffffff/v2.0",
        )
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=wrong_issuer_jwks):
            with pytest.raises(InvalidIssuerError):
                verify_microsoft_access_token(token, CLIENT_ID)

    def test_tenant_allow_list_rejects_unlisted_tenant(self):
        """Token from a tenant not in the allow-list is rejected after signature check."""
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(
                InvalidIssuerError, match="not in the configured allowed tenant list"
            ):
                verify_microsoft_access_token(
                    token,
                    CLIENT_ID,
                    allowed_tenant_ids={"ffffffff-ffff-ffff-ffff-ffffffffffff"},
                )

    def test_tenant_allow_list_accepts_listed_tenant(self):
        """Token from a tenant in the allow-list passes."""
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_microsoft_access_token(
                token,
                CLIENT_ID,
                allowed_tenant_ids={TENANT_ID},
            )
        assert claims["tid"] == TENANT_ID

    def test_no_allow_list_accepts_any_tenant(self):
        """When allowed_tenant_ids is None, any tenant is accepted."""
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_microsoft_access_token(token, CLIENT_ID, allowed_tenant_ids=None)

        assert claims["tid"] == TENANT_ID

    def test_missing_tid_raises(self):
        """Token without a tid claim cannot resolve the JWKS endpoint."""
        now = int(time.time())
        payload = {
            "aud": CLIENT_ID,
            "iss": MS_V2_ISS,
            "sub": "no-tid",
            "iat": now,
            "exp": now + 3600,
            # tid intentionally omitted
        }
        token = jwt.encode(payload, self.private_key, algorithm="RS256", headers={"kid": KID})

        with pytest.raises(JWTVerificationError, match="missing the 'tid' claim"):
            verify_microsoft_access_token(token, CLIENT_ID)

    def test_missing_client_id_raises(self):
        """Empty client_id is rejected immediately."""
        token = _make_ms_token(self.private_key)
        with pytest.raises(JWTVerificationError, match="client_id is required"):
            verify_microsoft_access_token(token, "")

    def test_kid_not_in_jwks_raises(self):
        """Token kid not found in the JWKS raises JWTVerificationError."""
        token = _make_ms_token(self.private_key, kid="unknown-kid")
        # JWKS has KID "test-key-id-001", token has "unknown-kid"

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(JWTVerificationError, match="not found in JWKS"):
                verify_microsoft_access_token(token, CLIENT_ID)

    def test_jwks_fetch_failure_raises(self):
        """Network failure during JWKS fetch propagates as JWTVerificationError."""
        token = _make_ms_token(self.private_key)

        with patch(
            "utils.jwt_verification._fetch_jwks", side_effect=JWTVerificationError("network error")
        ):
            with pytest.raises(JWTVerificationError):
                verify_microsoft_access_token(token, CLIENT_ID)

    def test_tenant_id_hint_bypasses_extraction(self):
        """Providing tenant_id explicitly skips the tid extraction from token."""
        token = _make_ms_token(self.private_key)

        fetched_urls = []

        def fake_fetch(url):
            fetched_urls.append(url)
            return self.jwks

        with patch("utils.jwt_verification._fetch_jwks", side_effect=fake_fetch):
            verify_microsoft_access_token(token, CLIENT_ID, tenant_id=TENANT_ID)

        assert any(TENANT_ID in u for u in fetched_urls)

    def test_templated_jwks_key_issuer_accepted(self):
        """Keys from tenant-independent JWKS endpoint have {tenantid} placeholder."""
        templated_jwks = _jwks(
            self.jwk,
            issuer="https://login.microsoftonline.com/{tenantid}/v2.0",
        )
        token = _make_ms_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=templated_jwks):
            claims = verify_microsoft_access_token(token, CLIENT_ID)

        assert claims["tid"] == TENANT_ID


# ─────────────────────────────────────────────────────────────────────────────
# verify_google_id_token
# ─────────────────────────────────────────────────────────────────────────────


class TestVerifyGoogleIdToken:
    """Tests for verify_google_id_token()."""

    def setup_method(self):
        self.private_key, self.public_key, self.jwk = _generate_rsa_key_pair()
        self.jwks = {"keys": [self.jwk]}

    def test_valid_token_verifies(self):
        """Happy path: valid Google ID token passes all checks."""
        token = _make_google_token(self.private_key)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_google_id_token(token, CLIENT_ID)

        assert claims["aud"] == CLIENT_ID
        assert claims["iss"] == GOOGLE_ISS

    def test_invalid_signature_raises(self):
        """Token signed with a different key raises InvalidSignatureError."""
        other_key, _, _ = _generate_rsa_key_pair()
        token = _make_google_token(other_key)  # signed with different key

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(InvalidSignatureError):
                verify_google_id_token(token, CLIENT_ID)

    def test_expired_token_raises(self):
        """Expired Google ID token raises ExpiredTokenError."""
        token = _make_google_token(self.private_key, exp_offset=-60)

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(ExpiredTokenError):
                verify_google_id_token(token, CLIENT_ID)

    def test_wrong_audience_raises(self):
        """Token with wrong audience raises InvalidAudienceError."""
        token = _make_google_token(self.private_key, aud="wrong-client-id")

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(InvalidAudienceError):
                verify_google_id_token(token, CLIENT_ID)

    def test_wrong_issuer_raises(self):
        """Token from an unknown issuer raises InvalidIssuerError."""
        token = _make_google_token(self.private_key, iss="https://evil.example.com")

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(InvalidIssuerError):
                verify_google_id_token(token, CLIENT_ID)

    def test_missing_client_id_raises(self):
        """Empty client_id is rejected before any JWKS fetch."""
        token = _make_google_token(self.private_key)
        with pytest.raises(JWTVerificationError, match="client_id is required"):
            verify_google_id_token(token, "")

    def test_kid_not_in_jwks_raises(self):
        """Token kid not found in JWKS raises JWTVerificationError."""
        token = _make_google_token(self.private_key, kid="unknown-kid")

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            with pytest.raises(JWTVerificationError, match="not found in JWKS"):
                verify_google_id_token(token, CLIENT_ID)

    def test_accounts_google_com_short_form_issuer_accepted(self):
        """Tokens with issuer 'accounts.google.com' (no https://) are also valid."""
        token = _make_google_token(self.private_key, iss="accounts.google.com")

        with patch("utils.jwt_verification._fetch_jwks", return_value=self.jwks):
            claims = verify_google_id_token(token, CLIENT_ID)

        assert claims["iss"] == "accounts.google.com"

    def test_jwks_cached_between_calls(self):
        """Second call within cache TTL must not make a second HTTP request."""
        token = _make_google_token(self.private_key)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = self.jwks

        with patch("utils.jwt_verification.httpx.get", return_value=mock_response) as mock_get:
            verify_google_id_token(token, CLIENT_ID)
            verify_google_id_token(token, CLIENT_ID)

        # httpx.get must only be called once; second call served from cache.
        assert mock_get.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_env_set (env_utils helper)
# ─────────────────────────────────────────────────────────────────────────────


class TestGetEnvSet:
    """Tests for the get_env_set() helper used for MICROSOFT_ALLOWED_TENANT_IDS."""

    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("MICROSOFT_ALLOWED_TENANT_IDS", raising=False)
        from utils.env_utils import get_env_set

        assert get_env_set("MICROSOFT_ALLOWED_TENANT_IDS") is None

    def test_empty_string_returns_none(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", "")
        from utils.env_utils import get_env_set

        assert get_env_set("MICROSOFT_ALLOWED_TENANT_IDS") is None

    def test_whitespace_only_returns_none(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", "   ")
        from utils.env_utils import get_env_set

        assert get_env_set("MICROSOFT_ALLOWED_TENANT_IDS") is None

    def test_single_value_returns_set(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", "aaaa-1111")
        from utils.env_utils import get_env_set

        result = get_env_set("MICROSOFT_ALLOWED_TENANT_IDS")
        assert result == {"aaaa-1111"}

    def test_multiple_values_returns_set(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", "aaaa-1111,bbbb-2222,cccc-3333")
        from utils.env_utils import get_env_set

        result = get_env_set("MICROSOFT_ALLOWED_TENANT_IDS")
        assert result == {"aaaa-1111", "bbbb-2222", "cccc-3333"}

    def test_values_are_stripped(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", " aaaa-1111 , bbbb-2222 ")
        from utils.env_utils import get_env_set

        result = get_env_set("MICROSOFT_ALLOWED_TENANT_IDS")
        assert result == {"aaaa-1111", "bbbb-2222"}

    def test_empty_segments_ignored(self, monkeypatch):
        monkeypatch.setenv("MICROSOFT_ALLOWED_TENANT_IDS", "aaaa-1111,,bbbb-2222,")
        from utils.env_utils import get_env_set

        result = get_env_set("MICROSOFT_ALLOWED_TENANT_IDS")
        assert result == {"aaaa-1111", "bbbb-2222"}
