from __future__ import annotations

import pytest

from connectors.opensearch_snapshot import endpoint_policy as ep
from connectors.opensearch_snapshot.endpoint_policy import EndpointPolicyError, validate_endpoint


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", raising=False)
    monkeypatch.delenv("OPENRAG_SNAPSHOT_REQUIRE_ENDPOINT_ALLOWLIST", raising=False)
    table = {
        "s3.example.com": ["93.184.216.34"],
        "minio.internal": ["10.0.0.5"],
        "multi.example.com": ["93.184.216.34", "10.0.0.7"],
        "meta.example.com": ["169.254.169.254"],
        "meta6.example.com": ["fd00:ec2::254"],
        "loop.example.com": ["127.0.0.1"],
        "v6.example.com": ["2606:2800:220:1:248:1893:25c8:1946"],
    }
    monkeypatch.setattr(
        ep,
        "_resolve",
        lambda host, port: (
            table.get(host)
            or (_ for _ in ()).throw(EndpointPolicyError("endpoint host cannot be resolved"))
        ),
    )


def test_none_and_blank_mean_aws_default():
    assert validate_endpoint(None) is None
    assert validate_endpoint("  ") is None


def test_public_endpoint_is_accepted_and_normalised():
    assert validate_endpoint("https://s3.example.com/") == "https://s3.example.com"
    assert validate_endpoint("http://S3.Example.com:9000") == "http://s3.example.com:9000"
    assert (
        validate_endpoint("https://[2606:2800:220:1:248:1893:25c8:1946]")
        == "https://[2606:2800:220:1:248:1893:25c8:1946]"
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://s3.example.com",
        "file:///etc/passwd",
        "s3.example.com",
        "https://user:pw@s3.example.com",
        "https://user@s3.example.com",
        "https://s3.example.com/bucket",
        "https://s3.example.com/?x=1",
        "https://s3.example.com/#f",
        "https://",
        "https://s3.example.com:notaport",
    ],
)
def test_malformed_or_credentialed_urls_rejected(url):
    with pytest.raises(EndpointPolicyError):
        validate_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:9000",
        "http://localhost:9000",  # resolved below
        "http://10.1.2.3",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://[::1]",
        "http://[fe80::1]",
        "http://[fc00::1]",
        "http://100.64.0.1",
        "http://[::ffff:127.0.0.1]",
        "http://minio.internal:9000",
        "http://loop.example.com",
        "http://multi.example.com",  # one private record is enough
    ],
)
def test_private_destinations_blocked_by_default(url, monkeypatch):
    monkeypatch.setattr(
        ep,
        "_resolve",
        lambda host, port: {
            "localhost": ["127.0.0.1"],
            "minio.internal": ["10.0.0.5"],
            "loop.example.com": ["127.0.0.1"],
            "multi.example.com": ["93.184.216.34", "10.0.0.7"],
        }[host],
    )
    with pytest.raises(EndpointPolicyError):
        validate_endpoint(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254",
        "http://169.254.1.1:80",
        "http://meta.example.com",
        "http://meta6.example.com",
        "http://[fd00:ec2::254]",
        "http://0.0.0.0",
        "http://0.1.2.3",
        "http://[::]",
        "http://224.0.0.1",
        "http://[ff02::1]",
    ],
)
def test_metadata_and_special_ranges_always_blocked(url, monkeypatch):
    for allow in ("", "169.254.169.254,meta.example.com,meta6.example.com,*.example.com,0.0.0.0"):
        monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", allow)
        with pytest.raises(EndpointPolicyError):
            validate_endpoint(url)


@pytest.mark.parametrize(
    ("allow", "url", "ok"),
    [
        ("minio.internal", "http://minio.internal:9000", True),
        ("minio.internal:9000", "http://minio.internal:9000", True),
        ("minio.internal:9000", "http://minio.internal:9001", False),
        ("*.internal", "http://minio.internal", True),
        ("*.internal", "http://internal", False),
        ("*.internal:9000", "http://minio.internal:9000", True),
        ("other.internal", "http://minio.internal", False),
        ("10.0.0.5", "http://10.0.0.5:9000", True),
        ("127.0.0.1:9100", "http://127.0.0.1:9100", True),
        ("127.0.0.1:9100", "http://127.0.0.1:9101", False),
        ("[::1]:9000", "http://[::1]:9000", True),
    ],
)
def test_allowlist_matching(allow, url, ok, monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", allow)
    monkeypatch.setattr(ep, "_resolve", lambda host, port: ["10.0.0.5"])
    if ok:
        assert validate_endpoint(url) == url
    else:
        with pytest.raises(EndpointPolicyError):
            validate_endpoint(url)


def test_require_allowlist_applies_to_public_endpoints(monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_REQUIRE_ENDPOINT_ALLOWLIST", "true")
    with pytest.raises(EndpointPolicyError):
        validate_endpoint("https://s3.example.com")
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "s3.example.com")
    assert validate_endpoint("https://s3.example.com") == "https://s3.example.com"


def test_unresolvable_host_rejected():
    with pytest.raises(EndpointPolicyError):
        validate_endpoint("https://nope.example.com")


def test_dns_resolution_failure_is_policy_error(monkeypatch):
    import socket

    monkeypatch.undo()
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("nx"))
    )
    with pytest.raises(EndpointPolicyError):
        validate_endpoint("https://definitely-not-real.invalid")


def test_allowlisted_private_endpoint_must_still_avoid_metadata(monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "multi.example.com")
    monkeypatch.setattr(ep, "_resolve", lambda host, port: ["10.0.0.7", "169.254.169.254"])
    with pytest.raises(EndpointPolicyError):
        validate_endpoint("http://multi.example.com")
