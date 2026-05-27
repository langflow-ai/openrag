import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import utils  # noqa: E402


@pytest.fixture(autouse=True)
def clear_public_key_cache():
    utils._ISSUER_PUBLIC_KEY_CACHE.clear()
    yield
    utils._ISSUER_PUBLIC_KEY_CACHE.clear()


def _make_es256_token(issuer: str) -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": issuer,
            "sub": "system:serviceaccount:tenant:wxd-openrag-be",
            "exp": now + 900,
            "iat": now,
            "roles": ["access_all"],
        },
        private_key,
        algorithm="ES256",
        headers={"typ": "JWT"},
    )
    return token, public_pem


def test_verify_jwt_from_issuer_fetches_public_key_and_validates_es256_token():
    issuer = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/workload"
    token, public_pem = _make_es256_token(issuer)

    response = MagicMock()
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"public_key": public_pem}

    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("config.utils.httpx.Client", return_value=client):
        claims = utils.verify_jwt_from_issuer(
            f"Bearer {token}",
            allowed_issuer_prefixes=(
                "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/",
            ),
            verify_tls=False,
        )

    assert claims is not None
    assert claims["iss"] == issuer
    assert claims["roles"] == ["access_all"]
    client.get.assert_called_once_with(issuer)


def test_verify_jwt_from_issuer_rejects_issuer_that_only_matches_as_string_prefix():
    issuer = (
        "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082"
        ".evil.example/keys/workload"
    )
    token, _ = _make_es256_token(issuer)

    with patch("config.utils.httpx.Client") as client_factory:
        claims = utils.verify_jwt_from_issuer(
            token,
            allowed_issuer_prefixes=(
                "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082",
            ),
        )

    assert claims is None
    client_factory.assert_not_called()


def test_verify_jwt_from_issuer_rejects_unallowed_issuer_without_fetching_key():
    issuer = "https://evil.example.test/keys/workload"
    token, _ = _make_es256_token(issuer)

    with patch("config.utils.httpx.Client") as client_factory:
        claims = utils.verify_jwt_from_issuer(
            token,
            allowed_issuer_prefixes=("https://authserver-oidc-svc.openrag-control.svc/",),
        )

    assert claims is None
    client_factory.assert_not_called()


def test_verify_jwt_from_issuer_accepts_standard_jwks_response():
    issuer = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/workload"
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()

    def _b64(value: int) -> str:
        import base64

        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()

    jwks = {
        "keys": [
            {
                "alg": "ES256",
                "crv": "P-256",
                "kty": "EC",
                "use": "sig",
                "x": _b64(public_numbers.x),
                "y": _b64(public_numbers.y),
            }
        ]
    }

    now = int(time.time())
    token = jwt.encode(
        {
            "iss": issuer,
            "sub": "system:serviceaccount:tenant:wxd-openrag-be",
            "exp": now + 900,
            "iat": now,
        },
        private_key,
        algorithm="ES256",
    )

    response = MagicMock()
    response.headers = {"content-type": "application/json"}
    response.json.return_value = jwks

    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("config.utils.httpx.Client", return_value=client):
        claims = utils.verify_jwt_from_issuer(
            token,
            allowed_issuer_prefixes=(
                "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/",
            ),
            verify_tls=False,
        )

    assert claims is not None
    assert claims["iss"] == issuer


def test_verify_jwt_from_issuer_accepts_raw_pem_response():
    issuer = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/raw"
    token, public_pem = _make_es256_token(issuer)

    response = MagicMock()
    response.headers = {"content-type": "application/x-pem-file"}
    response.json.side_effect = ValueError("not json")
    response.text = public_pem

    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("config.utils.httpx.Client", return_value=client):
        claims = utils.verify_jwt_from_issuer(
            token,
            allowed_issuer_prefixes=(
                "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082/keys/",
            ),
            verify_tls=False,
        )

    assert claims is not None
    assert claims["iss"] == issuer


def _patch_post_returning_token(token: str):
    post_response = MagicMock()
    post_response.raise_for_status.return_value = None
    post_response.json.return_value = {"token": token}

    post_client = MagicMock()
    post_client.__enter__.return_value = post_client
    post_client.post.return_value = post_response
    return post_client


def test_get_opensearch_service_token_verifies_returned_jwt(tmp_path):
    auth_server_url = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082"
    issuer = f"{auth_server_url}/keys/workload"
    token, public_pem = _make_es256_token(issuer)

    sa_token_file = tmp_path / "sa-token"
    sa_token_file.write_text("k8s-sa-token")

    post_client = _patch_post_returning_token(token)

    get_response = MagicMock()
    get_response.headers = {"content-type": "application/x-pem-file"}
    get_response.json.side_effect = ValueError("not json")
    get_response.text = public_pem
    get_response.raise_for_status.return_value = None

    get_client = MagicMock()
    get_client.__enter__.return_value = get_client
    get_client.get.return_value = get_response

    with patch("config.utils.httpx.Client", side_effect=[post_client, get_client]):
        result = utils.get_opensearch_service_token(
            auth_server_url,
            tenant_id="openrag",
            k8s_sa_token_path=str(sa_token_file),
        )

    assert result == token


def test_get_opensearch_service_token_rejects_token_from_unexpected_issuer(tmp_path):
    auth_server_url = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082"
    issuer = "https://attacker.example/keys/workload"
    token, _ = _make_es256_token(issuer)

    sa_token_file = tmp_path / "sa-token"
    sa_token_file.write_text("k8s-sa-token")

    post_client = _patch_post_returning_token(token)

    with patch("config.utils.httpx.Client", side_effect=[post_client]):
        result = utils.get_opensearch_service_token(
            auth_server_url,
            tenant_id="openrag",
            k8s_sa_token_path=str(sa_token_file),
        )

    assert result is None


def test_get_opensearch_service_token_skips_verification_when_disabled(tmp_path):
    auth_server_url = "https://authserver-oidc-svc.openrag-control.svc.cluster.local:8082"
    issuer = "https://attacker.example/keys/workload"
    token, _ = _make_es256_token(issuer)

    sa_token_file = tmp_path / "sa-token"
    sa_token_file.write_text("k8s-sa-token")

    post_client = _patch_post_returning_token(token)

    with patch("config.utils.httpx.Client", side_effect=[post_client]):
        result = utils.get_opensearch_service_token(
            auth_server_url,
            tenant_id="openrag",
            k8s_sa_token_path=str(sa_token_file),
            verify_token=False,
        )

    assert result == token
