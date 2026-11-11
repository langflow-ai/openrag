"""Backend -> Docling Serve TLS (one-way), via config.settings._docling_tls_kwargs().

With interpod TLS on, the operator fronts docling-serve with a TLS-terminating
sidecar and sets DOCLING_SERVE_URL=https://..., DOCLING_SERVE_CA_CERT and
DOCLING_SERVE_VERIFY_SSL=true. With it off, the URL stays http:// and the CA is
empty, and behaviour must match what it was before DOCLING_SERVE_CA_CERT existed.

Handshakes run against a real local HTTPS server whose certificate is signed by
a throwaway CA, so these tests check what is actually trusted (and whether a
client certificate is sent), not how the ssl module happens to be called.
"""

import datetime
import json
import os
import socketserver
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import config.settings as settings

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


# ---------------------------------------------------------------------------
# Throwaway PKI and a local HTTPS "docling-serve"
# ---------------------------------------------------------------------------


def _key_usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not ca,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


def _issue(
    subject: str, issuer_key, issuer_name: x509.Name | None, *, ca: bool, eku=None, san=None
):
    """Return (cert, key). Extensions satisfy the X509 strict checks on by default in 3.13+."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    signing_key = issuer_key or key
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_name or name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(_key_usage(ca=ca), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(signing_key.public_key()),
            critical=False,
        )
    )
    if eku:
        builder = builder.add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
    if san:
        builder = builder.add_extension(x509.SubjectAlternativeName(san), critical=False)
    return builder.sign(signing_key, hashes.SHA256()), key


def _write(path: Path, cert, key=None) -> None:
    path.with_suffix(".crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    if key is not None:
        path.with_suffix(".key").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """Interpod CA, a docling-serve server cert, and a be-tls-style client cert."""
    directory = tmp_path_factory.mktemp("docling-pki")
    ca_cert, ca_key = _issue("test-interpod-ca", None, None, ca=True)
    server_cert, server_key = _issue(
        "docling-serve",
        ca_key,
        ca_cert.subject,
        ca=False,
        eku=ExtendedKeyUsageOID.SERVER_AUTH,
        san=[x509.IPAddress(IPv4Address("127.0.0.1"))],
    )
    client_cert, client_key = _issue(
        "be-tls", ca_key, ca_cert.subject, ca=False, eku=ExtendedKeyUsageOID.CLIENT_AUTH
    )
    _write(directory / "ca", ca_cert)
    _write(directory / "server", server_cert, server_key)
    _write(directory / "client", client_cert, client_key)
    return SimpleNamespace(
        ca=str(directory / "ca.crt"),
        server_cert=str(directory / "server.crt"),
        server_key=str(directory / "server.key"),
        client_cert=str(directory / "client.crt"),
        client_key=str(directory / "client.key"),
    )


class _DoclingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Records the client certificate, if any, the caller presented.
        self.server.client_certs.append(self.request.getpeercert())
        body = json.dumps({"status": "ok", "docling-serve": "test"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _DoclingServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind() does a reverse-DNS lookup (getfqdn) that can
        # stall for ~30s on an uncached resolver; the server name isn't needed.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


@pytest.fixture(scope="module")
def _https_server(pki):
    httpd = _DoclingServer(("127.0.0.1", 0), _DoclingHandler)
    httpd.client_certs = []
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(pki.server_cert, pki.server_key)
    # Ask for (but don't require) a client cert, so the tests can see whether
    # the backend volunteers one. The real sidecar doesn't ask at all.
    ctx.load_verify_locations(pki.ca)
    ctx.verify_mode = ssl.CERT_OPTIONAL
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture
def docling_serve(_https_server):
    _https_server.client_certs.clear()
    return SimpleNamespace(
        url=f"https://127.0.0.1:{_https_server.server_address[1]}",
        client_certs=_https_server.client_certs,
    )


@pytest.fixture
def docling_tls(monkeypatch):
    """Set the Docling TLS settings _docling_tls_kwargs() reads at call time."""

    def configure(*, verify: bool, ca_cert: str | None):
        monkeypatch.setattr(settings, "DOCLING_SERVE_VERIFY_SSL", verify)
        monkeypatch.setattr(settings, "DOCLING_SERVE_CA_CERT", ca_cert)

    return configure


# ---------------------------------------------------------------------------
# _docling_tls_kwargs()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("verify", "ca_cert"),
    [(True, None), (True, ""), (False, None), (False, "")],
    ids=["verify-no-ca", "verify-empty-ca", "no-verify-no-ca", "no-verify-empty-ca"],
)
def test_without_ca_cert_verify_bool_passes_through_unchanged(docling_tls, verify, ca_cert):
    """No CA configured (TLS-disabled clusters, compose, local dev): same as before."""
    docling_tls(verify=verify, ca_cert=ca_cert)
    assert settings._docling_tls_kwargs() == {"verify": verify}


def test_explicit_verify_false_wins_over_ca_cert(docling_tls, pki):
    docling_tls(verify=False, ca_cert=pki.ca)
    assert settings._docling_tls_kwargs() == {"verify": False}


def test_ca_cert_builds_context_that_verifies_against_it(docling_tls, pki):
    docling_tls(verify=True, ca_cert=pki.ca)
    ctx = settings._docling_tls_kwargs()["verify"]

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    trusted = [dict(rdn[0] for rdn in c["subject"]) for c in ctx.get_ca_certs()]
    assert {"commonName": "test-interpod-ca"} in trusted


# ---------------------------------------------------------------------------
# Real handshakes
# ---------------------------------------------------------------------------


def test_handshake_succeeds_with_configured_ca(docling_tls, pki, docling_serve):
    docling_tls(verify=True, ca_cert=pki.ca)
    with httpx.Client(**settings._docling_tls_kwargs()) as client:
        assert client.get(f"{docling_serve.url}/version").status_code == 200


def test_handshake_fails_without_ca_when_verifying(docling_tls, docling_serve, monkeypatch):
    """Without DOCLING_SERVE_CA_CERT the interpod cert is untrusted, not silently accepted."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    docling_tls(verify=True, ca_cert=None)
    with (
        httpx.Client(**settings._docling_tls_kwargs()) as client,
        pytest.raises(httpx.ConnectError),
    ):
        client.get(f"{docling_serve.url}/version")


def test_handshake_succeeds_with_verification_disabled(docling_tls, docling_serve):
    docling_tls(verify=False, ca_cert=None)
    with httpx.Client(**settings._docling_tls_kwargs()) as client:
        assert client.get(f"{docling_serve.url}/version").status_code == 200


def test_no_client_certificate_even_when_backend_has_one(
    docling_tls, pki, docling_serve, monkeypatch
):
    """One-way TLS: the backend's be-tls cert (used for mTLS to Langflow) is not sent."""
    # Control: the server does record a client cert when one is presented.
    ctx = ssl.create_default_context(cafile=pki.ca)
    ctx.load_cert_chain(pki.client_cert, pki.client_key)
    with httpx.Client(verify=ctx) as client:
        client.get(f"{docling_serve.url}/version")
    assert docling_serve.client_certs[-1]

    monkeypatch.setattr(settings, "OPENRAG_TLS_CERT_PATH", pki.client_cert)
    monkeypatch.setattr(settings, "OPENRAG_TLS_KEY_PATH", pki.client_key)
    docling_tls(verify=True, ca_cert=pki.ca)
    with httpx.Client(**settings._docling_tls_kwargs()) as client:
        client.get(f"{docling_serve.url}/version")
    assert docling_serve.client_certs[-1] is None


# ---------------------------------------------------------------------------
# Call sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_docling_http_client_uses_docling_tls(docling_tls, pki, docling_serve):
    """AppClients.docling_http_client backs DoclingService ingestion and check_docling."""
    docling_tls(verify=True, ca_cert=pki.ca)
    client = settings.AppClients()._create_docling_http_client()
    try:
        assert (await client.get(f"{docling_serve.url}/version")).status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_docling_service_default_client_uses_docling_tls(
    docling_tls, pki, docling_serve, monkeypatch
):
    from services.docling_service import DoclingService

    monkeypatch.setattr(DoclingService, "_default_client", None)
    docling_tls(verify=True, ca_cert=pki.ca)
    client = DoclingService(docling_url=docling_serve.url)._get_client()
    try:
        assert (await client.get(f"{docling_serve.url}/version")).status_code == 200
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_docling_health_endpoint_uses_docling_tls(
    docling_tls, pki, docling_serve, monkeypatch
):
    import api.docling as docling_api

    monkeypatch.setattr(docling_api, "DOCLING_SERVICE_URL", docling_serve.url)
    docling_tls(verify=True, ca_cert=pki.ca)
    response = await docling_api.health(MagicMock(), user=None)

    assert response.status_code == 200
    assert json.loads(response.body)["status"] == "healthy"


# ---------------------------------------------------------------------------
# Import-time env parsing (fresh interpreter per case)
# ---------------------------------------------------------------------------

_PROBE = """
import json
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False  # keep a developer's .env out of it
import config.settings as s
verify = s._docling_tls_kwargs()["verify"]
print(json.dumps({
    "verify_ssl": s.DOCLING_SERVE_VERIFY_SSL,
    "ca_cert": s.DOCLING_SERVE_CA_CERT,
    "httpx_verify": verify if isinstance(verify, bool) else type(verify).__name__,
}))
"""


def _import_settings(env: dict[str, str]) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("DOCLING_SERVE_VERIFY_SSL", None)
    merged.pop("DOCLING_SERVE_CA_CERT", None)
    merged.update(env)
    merged["PYTHONPATH"] = str(SRC)
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env=merged,
        cwd=str(ROOT),
    )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, {"verify_ssl": True, "ca_cert": None, "httpx_verify": True}),
        (
            {"DOCLING_SERVE_VERIFY_SSL": "false", "DOCLING_SERVE_CA_CERT": ""},
            {"verify_ssl": False, "ca_cert": "", "httpx_verify": False},
        ),
        (
            {"DOCLING_SERVE_VERIFY_SSL": "true", "DOCLING_SERVE_CA_CERT": "{ca}"},
            {"verify_ssl": True, "ca_cert": "{ca}", "httpx_verify": "SSLContext"},
        ),
    ],
    ids=["unset-defaults-to-verify", "operator-interpod-tls-off", "operator-interpod-tls-on"],
)
def test_env_parsing(pki, env, expected):
    env = {k: v.format(ca=pki.ca) for k, v in env.items()}
    expected = {k: v.format(ca=pki.ca) if isinstance(v, str) else v for k, v in expected.items()}

    result = _import_settings(env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == expected


def test_missing_ca_cert_path_fails_at_startup():
    result = _import_settings({"DOCLING_SERVE_CA_CERT": "/nonexistent/interpod-ca/ca.crt"})

    assert result.returncode != 0
    assert "DOCLING_SERVE_CA_CERT path does not exist" in result.stderr
