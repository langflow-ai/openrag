"""Destination allowlist + IP-range guard for outbound URL ingestion (VULN-13906).

Two independent layers, both required:

1. Host allowlist (``OPENRAG_URL_INGEST_ALLOWED_HOSTS``) — fail-closed. An
   unset/blank allowlist blocks every host. This is the primary control: an
   attacker-chosen hostname that happens to resolve to a "public-looking" IP
   (as in the VULN-13906 report, where a non-RFC1918 internal address was
   reachable) is blocked here even though no IP-range check would catch it.
2. IP-range check on every resolved address — defense in depth against DNS
   rebinding, where an allowlisted hostname is made to resolve to a private/
   internal IP after the allowlist check passes.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from config.settings import OPENRAG_URL_INGEST_ALLOWED_HOSTS

# Shared/Carrier-Grade NAT address space (RFC 6598). Not covered by
# ipaddress.IPv4Address.is_private in the stdlib.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class SSRFBlockedError(ValueError):
    """Raised when a URL fails the destination allowlist or IP-safety check."""


def is_host_allowlisted(host: str) -> bool:
    """Return True only if `host` matches an entry in OPENRAG_URL_INGEST_ALLOWED_HOSTS.

    Fail-closed: an unset/empty allowlist matches nothing.
    """
    if not OPENRAG_URL_INGEST_ALLOWED_HOSTS:
        return False

    host = host.strip().lower().rstrip(".")
    for entry in OPENRAG_URL_INGEST_ALLOWED_HOSTS:
        entry = entry.strip().lower().rstrip(".")
        if not entry:
            continue
        if entry.startswith("*."):
            suffix = entry[1:]  # keep the leading dot, e.g. ".example.com"
            bare = entry[2:]  # e.g. "example.com"
            if host == bare or host.endswith(suffix):
                return True
        elif host == entry:
            return True
    return False


def _is_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast or ip.is_unspecified:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK


def resolve_and_check_ip_safety(host: str) -> None:
    """Resolve `host` and raise SSRFBlockedError if any resolved IP is unsafe.

    Blocks RFC1918, loopback, link-local (including the 169.254.169.254 cloud
    metadata endpoint), IPv6 ULA, CGNAT, and other reserved/multicast ranges —
    regardless of whether the hostname itself is allowlisted, so a hostname
    that later resolves (or is rebound via DNS) to an internal address is
    still blocked.
    """
    try:
        # Literal IP fast path avoids a DNS lookup and handles bracketed IPv6.
        addr = ipaddress.ip_address(host)
        addrinfo_ips = [addr]
    except ValueError:
        try:
            results = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise SSRFBlockedError(f"Could not resolve host: {host}") from exc
        addrinfo_ips = [ipaddress.ip_address(r[4][0]) for r in results]

    for ip in addrinfo_ips:
        if _is_unsafe_ip(ip):
            raise SSRFBlockedError(
                f"URL ingestion blocked: {host} resolves to a non-routable/internal "
                f"address ({ip}), which is never allowed regardless of the host allowlist."
            )


def assert_url_ingest_allowed(url: str) -> None:
    """Raise SSRFBlockedError unless `url`'s host passes both the allowlist and IP checks.

    Callers should treat SSRFBlockedError as a normal validation failure (400-style),
    not an unexpected server error.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise SSRFBlockedError(f"URL ingestion blocked: could not parse a host from {url!r}")

    if not is_host_allowlisted(host):
        raise SSRFBlockedError(
            f"URL ingestion blocked: host '{host}' is not in OPENRAG_URL_INGEST_ALLOWED_HOSTS."
        )

    resolve_and_check_ip_safety(host)
