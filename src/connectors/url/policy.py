"""Validation shared by URL source API and crawler.

This is deliberately host-side: URL crawling has no sandbox or proxy
assumption. Every URL is normalized before entering the frontier and every
destination is revalidated by the fetcher before it is contacted.
"""

from __future__ import annotations

import ipaddress
import posixpath
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class CrawlPolicyError(ValueError):
    pass


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
    path = parsed.path or "/"
    normalized_path = posixpath.normpath(path)
    if path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path += "/"
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, normalized_path, parsed.query, ""))


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global and address not in ipaddress.ip_network("100.64.0.0/10")


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    records = socket.getaddrinfo(normalize_host(host), port, type=socket.SOCK_STREAM)
    addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not public_ip(address) for address in addresses):
        raise CrawlPolicyError("destination does not resolve exclusively to public addresses")
    return addresses


def _path(value: str) -> str:
    value = value.strip()
    if not value.startswith("/") or "?" in value or "#" in value:
        raise CrawlPolicyError("paths must begin with / and cannot contain a query or fragment")
    return value


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
    max_pages: int = 250
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
        includes = self.include_paths or ((seed.path or "/",) if self.scope == "path" else ("/",))
        return any(_matches_path(path, p) for p in includes) and not any(
            _matches_path(path, p) for p in self.exclude_paths
        )

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}
