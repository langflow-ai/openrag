"""SSRF policy for operator-unvetted S3 endpoints (source and staging).

Rules (all evaluated on every resolved A/AAAA address):

* only ``http``/``https``, no userinfo, no path/query/fragment;
* instance-metadata and unspecified/multicast ranges are always blocked, even
  if allowlisted (``169.254.0.0/16``, ``fd00:ec2::254``, ``0.0.0.0/8``, ...);
* loopback/private/link-local/CGNAT/ULA/other non-global addresses are only
  accepted when ``host`` or ``host:port`` is in ``OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS``;
* with ``OPENRAG_SNAPSHOT_REQUIRE_ENDPOINT_ALLOWLIST=true`` every endpoint must
  be allowlisted.

``None`` means "AWS default endpoint" and is always accepted.

Enforcement at the real destination: validating the configured URL once is not
enough, because the SDK may rewrite it (virtual-host bucket subdomains) or retry.
Custom endpoints therefore always use path-style addressing, and
:func:`install_request_guard` re-applies this policy to the final host of every
request attempt (botocore ``before-send``, so retries are covered) and refuses
any request whose host is not the configured endpoint's.

Residual risk: the guard resolves the host immediately before the SDK connects,
but urllib3 performs its own lookup afterwards. A DNS-rebinding attacker who
controls the endpoint's DNS can still flip the answer inside that short window
(TOCTOU). Closing it needs a connection-level pin that the SDK does not offer;
hardened installs should set ``OPENRAG_SNAPSHOT_REQUIRE_ENDPOINT_ALLOWLIST=true``
so only operator-vetted hosts are ever contacted.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

from config.settings import (
    get_snapshot_allowed_endpoints,
    snapshot_endpoint_allowlist_required,
)


class EndpointPolicyError(ValueError):
    """The endpoint is not permitted. ``str()`` is safe to show to the user."""


_ALWAYS_BLOCKED_V4 = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
)
_ALWAYS_BLOCKED_V6 = (
    ipaddress.ip_network("fd00:ec2::/64"),
    ipaddress.ip_network("::/128"),
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _resolve(host: str, port: int) -> list[str]:
    """Resolve every A/AAAA record. Module-level so tests can replace it."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise EndpointPolicyError("endpoint host cannot be resolved") from exc
    return sorted({info[4][0].split("%", 1)[0] for info in infos})


def _canonical(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _always_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_multicast or ip.is_unspecified:
        return True
    nets = _ALWAYS_BLOCKED_V4 if ip.version == 4 else _ALWAYS_BLOCKED_V6
    return any(ip in net for net in nets)


def _is_allowlisted(host: str, port: int, entries: list[str]) -> bool:
    for entry in entries:
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.startswith("*."):
            suffix, _, suffix_port = entry[1:].partition(":")
            if host.endswith(suffix) and len(host) > len(suffix):
                if not suffix_port or suffix_port == str(port):
                    return True
            continue
        entry_host, entry_port = entry, None
        if entry.startswith("["):
            closing = entry.find("]")
            if closing != -1:
                entry_host = entry[1:closing]
                rest = entry[closing + 1 :]
                entry_port = rest[1:] if rest.startswith(":") else None
        elif entry.count(":") == 1:
            entry_host, _, entry_port = entry.partition(":")
        if entry_host == host and (entry_port is None or entry_port == str(port)):
            return True
    return False


def validate_endpoint(url: str | None) -> str | None:
    """Validate ``url`` and return it normalised (no trailing slash).

    Raises :class:`EndpointPolicyError` when the endpoint violates the policy.
    """
    if url is None or not str(url).strip():
        return None
    raw = str(url).strip()
    try:
        parts = urlsplit(raw)
        port = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise EndpointPolicyError("endpoint URL is malformed") from exc

    if parts.scheme not in ("http", "https"):
        raise EndpointPolicyError("endpoint must use http or https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise EndpointPolicyError("endpoint must not contain credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment or ";" in raw:
        raise EndpointPolicyError("endpoint must not contain a path, query or fragment")
    if not host:
        raise EndpointPolicyError("endpoint host is missing")

    host = host.lower().rstrip(".")
    effective_port = port or _DEFAULT_PORTS[parts.scheme]

    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        addresses = _resolve(host, effective_port)
    if not addresses:
        raise EndpointPolicyError("endpoint host cannot be resolved")

    allowlisted = _is_allowlisted(host, effective_port, get_snapshot_allowed_endpoints())
    if snapshot_endpoint_allowlist_required() and not allowlisted:
        raise EndpointPolicyError("endpoint is not in the allowed endpoint list")

    for address in addresses:
        ip = _canonical(address)
        if _always_blocked(ip):
            raise EndpointPolicyError("endpoint resolves to a blocked address range")
        if not ip.is_global and not allowlisted:
            raise EndpointPolicyError(
                "endpoint resolves to a private or local address and is not in the allowed endpoint list"
            )

    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    return f"{parts.scheme}://{netloc}"


def _origin(url: str) -> tuple[str, str, int]:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise EndpointPolicyError("request destination is malformed") from exc
    host = (parts.hostname or "").lower().rstrip(".")
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not host:
        raise EndpointPolicyError("request destination is malformed")
    return scheme, host, port or _DEFAULT_PORTS[scheme]


def check_request_destination(request_url: str, endpoint: str | None) -> None:
    """Refuse ``request_url`` unless it targets ``endpoint``'s origin and passes the policy *now*.

    ``endpoint`` is the already validated custom endpoint (``None``: AWS default,
    nothing to enforce). The configured endpoint is validated again, so a host
    that has started resolving to a blocked or private address is refused at
    request time.
    """
    if endpoint is None:
        return
    if _origin(request_url) != _origin(endpoint):
        raise EndpointPolicyError("request destination does not match the configured endpoint")
    validate_endpoint(endpoint)


def install_request_guard(client: Any, endpoint: str | None) -> None:
    """Enforce :func:`check_request_destination` on every request attempt of a botocore client."""
    if endpoint is None:
        return

    def guard(request: Any, **_kwargs: Any) -> None:
        check_request_destination(request.url, endpoint)

    client.meta.events.register("before-send", guard)
