import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import utils.ssrf_guard as ssrf_guard  # noqa: E402


@pytest.mark.parametrize(
    ("ip", "should_be_blocked"),
    [
        ("10.0.0.1", True),  # RFC1918
        ("172.16.5.5", True),  # RFC1918
        ("192.168.1.1", True),  # RFC1918
        ("127.0.0.1", True),  # loopback
        ("169.254.169.254", True),  # link-local / cloud metadata
        ("100.64.0.1", True),  # CGNAT — not covered by stdlib is_private
        (
            "9.30.87.233",
            False,
        ),  # the pentest's "non-RFC1918 internal" target — publicly-routable-looking
        ("8.8.8.8", False),  # public
    ],
)
def test_resolve_and_check_ip_safety_literal_ips(ip, should_be_blocked):
    if should_be_blocked:
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.resolve_and_check_ip_safety(ip)
    else:
        ssrf_guard.resolve_and_check_ip_safety(ip)  # must not raise


def test_is_host_allowlisted_unset_denies_all(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", None)
    assert ssrf_guard.is_host_allowlisted("example.com") is False


def test_is_host_allowlisted_empty_set_denies_all(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", set())
    assert ssrf_guard.is_host_allowlisted("example.com") is False


def test_is_host_allowlisted_exact_match(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"example.com"})
    assert ssrf_guard.is_host_allowlisted("example.com") is True
    assert ssrf_guard.is_host_allowlisted("EXAMPLE.COM") is True
    assert ssrf_guard.is_host_allowlisted("other.com") is False


def test_is_host_allowlisted_wildcard_suffix(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"*.example.com"})
    assert ssrf_guard.is_host_allowlisted("docs.example.com") is True
    assert ssrf_guard.is_host_allowlisted("example.com") is True
    assert ssrf_guard.is_host_allowlisted("notexample.com") is False
    assert ssrf_guard.is_host_allowlisted("example.com.evil.com") is False


def test_assert_url_ingest_allowed_denies_when_host_not_allowlisted(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"good.example.com"})
    with pytest.raises(ssrf_guard.SSRFBlockedError):
        ssrf_guard.assert_url_ingest_allowed("https://attacker.example/canary")


def test_assert_url_ingest_allowed_passes_for_allowlisted_public_host(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"docs.example.com"})

    def fake_getaddrinfo(host, port):
        assert host == "docs.example.com"
        return [(None, None, None, None, ("8.8.8.8", 0))]

    monkeypatch.setattr(ssrf_guard.socket, "getaddrinfo", fake_getaddrinfo)
    ssrf_guard.assert_url_ingest_allowed("https://docs.example.com/report")


def test_assert_url_ingest_allowed_blocks_allowlisted_host_resolving_to_private_ip(monkeypatch):
    monkeypatch.setattr(ssrf_guard, "OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"localhost"})
    # Even if an operator mistakenly allowlists "localhost", the IP-safety layer still blocks it.
    with pytest.raises(ssrf_guard.SSRFBlockedError):
        ssrf_guard.assert_url_ingest_allowed("http://localhost:9200/")
