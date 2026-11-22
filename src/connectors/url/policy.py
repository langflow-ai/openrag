"""Validation shared by URL source API and crawler.

This is deliberately host-side: URL crawling has no sandbox or proxy
assumption. Every URL is normalized before entering the frontier and every
destination is revalidated by the fetcher before it is contacted.
"""

from __future__ import annotations

import ipaddress
import posixpath
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class CrawlPolicyError(ValueError):
    pass


_AMBIGUOUS_ENCODED_PATH = re.compile(r"%(?:2e|2f|5c|25)", re.IGNORECASE)


def normalize_path(value: str) -> str:
    """Normalize an unambiguous URL path before applying crawl scope rules."""
    if "\\" in value or _AMBIGUOUS_ENCODED_PATH.search(value):
        raise CrawlPolicyError("URL path contains encoded traversal or separators")
    path = value or "/"
    normalized_path = posixpath.normpath(path)
    if path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    return normalized_path


def normalize_host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    if not host:
        raise CrawlPolicyError("URL must include a hostname")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise CrawlPolicyError("URL hostname is invalid") from exc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise CrawlPolicyError("IP-literal URLs are not permitted")


def canonicalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise CrawlPolicyError("URL is invalid") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise CrawlPolicyError("Only HTTP and HTTPS URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise CrawlPolicyError("URLs with embedded credentials are not permitted")
    host = normalize_host(parsed.hostname or "")
    try:
        port = parsed.port
    except ValueError as exc:
        raise CrawlPolicyError("URL port is invalid") from exc
    if port is not None and port not in {80, 443}:
        raise CrawlPolicyError("Only ports 80 and 443 are accepted")
    if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None
    normalized_path = normalize_path(parsed.path)
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, normalized_path, parsed.query, ""))


# NAT64 prefixes (RFC 6052, RFC 8215). A gateway translates these IPv6
# addresses into IPv4 ones, so an address in them is only as public as the
# IPv4 address it reaches. Python's ipaddress counts both prefixes as global.
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_USE = ipaddress.ip_network("64:ff9b:1::/48")
# Deprecated IPv4-compatible addresses (RFC 4291 section 2.5.5.1), such as
# ::a00:1 for 10.0.0.1. Python counts most of them as global; no public host
# is reached this way, so they are never allowed.
_IPV4_COMPATIBLE = ipaddress.ip_network("::/96")
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address.version == 6:
        if address in _NAT64_WELL_KNOWN:
            # The IPv4 destination is the last 32 bits; judge that instead.
            return public_ip(str(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)))
        if address in _NAT64_LOCAL_USE or address in _IPV4_COMPATIBLE:
            # Local-use NAT64 maps wherever the operator chooses, and
            # IPv4-compatible addresses are deprecated; neither is trusted.
            return False
    return address.is_global and address not in _SHARED_ADDRESS_SPACE


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(normalize_host(host), port, type=socket.SOCK_STREAM)
    addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
    if not addresses or any(not public_ip(address) for address in addresses):
        raise CrawlPolicyError("destination does not resolve exclusively to public addresses")
    return addresses


def _path(value: str) -> str:
    value = value.strip()
    if not value.startswith("/") or "?" in value or "#" in value:
        raise CrawlPolicyError("paths must begin with / and cannot contain a query or fragment")
    return normalize_path(value)


def _matches_path(path: str, prefix: str) -> bool:
    return prefix == "/" or path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")


@dataclass(frozen=True)
class CrawlSpec:
    seed_url: str
    scope: str = "path"
    allow_subdomains: bool = False
    additional_hosts: tuple[str, ...] = ()
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    max_pages: int = 1000
    max_depth: int = 4
    max_downloaded_mb: int = 128
    max_crawl_minutes: int = 15

    def __post_init__(self) -> None:
        seed = canonicalize_url(self.seed_url)
        if self.scope not in {"page", "path", "site"}:
            raise CrawlPolicyError("scope must be page, path, or site")
        if self.scope == "page" and (self.max_pages != 1 or self.max_depth != 0):
            raise CrawlPolicyError("page scope requires one page and depth zero")
        if not 1 <= self.max_pages <= 10_000 or not 0 <= self.max_depth <= 20:
            raise CrawlPolicyError("crawl limits are outside the permitted range")
        if not 1 <= self.max_downloaded_mb <= 2048 or not 1 <= self.max_crawl_minutes <= 60:
            raise CrawlPolicyError("crawl limits are outside the permitted range")
        object.__setattr__(self, "seed_url", seed)
        object.__setattr__(
            self,
            "additional_hosts",
            tuple(dict.fromkeys(normalize_host(h) for h in self.additional_hosts if h.strip())),
        )
        object.__setattr__(self, "include_paths", tuple(_path(p) for p in self.include_paths))
        object.__setattr__(self, "exclude_paths", tuple(_path(p) for p in self.exclude_paths))

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        host = normalize_host(urlsplit(self.seed_url).hostname or "")
        extra = tuple(self.additional_hosts)
        return (host, *extra)

    def allows(self, value: str) -> bool:
        try:
            url = canonicalize_url(value)
        except CrawlPolicyError:
            return False
        parsed, seed = urlsplit(url), urlsplit(self.seed_url)
        host = normalize_host(parsed.hostname or "")
        seed_host = normalize_host(seed.hostname or "")
        host_allowed = host == seed_host or host in self.additional_hosts
        if self.allow_subdomains and host.endswith("." + seed_host):
            host_allowed = True
        if not host_allowed:
            return False
        path = parsed.path or "/"
        if self.scope == "path" and not _matches_path(path, seed.path or "/"):
            return False
        if self.include_paths and not any(_matches_path(path, p) for p in self.include_paths):
            return False
        return not any(_matches_path(path, p) for p in self.exclude_paths)

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}
