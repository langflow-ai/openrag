"""Small bounded crawler used only by the managed URL connector."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from .document import WebDocument, html_to_document
from .policy import CrawlPolicyError, CrawlSpec, canonicalize_url, resolve_public_addresses

USER_AGENT = "OpenRAG URL connector (+https://openrag.ai)"
MAX_REDIRECTS = 5


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.noindex = False
        self.nofollow = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag.lower() == "meta" and values.get("name", "").lower() == "robots":
            robots = values.get("content", "").lower()
            self.noindex = "noindex" in robots
            self.nofollow = "nofollow" in robots


@dataclass(frozen=True)
class CrawledPage:
    canonical_url: str
    final_url: str
    depth: int
    document: WebDocument | None
    noindex: bool = False
    error: str | None = None


@dataclass(frozen=True)
class CrawlResult:
    pages: tuple[CrawledPage, ...]
    complete: bool
    capped: bool
    reason: str | None = None


async def _fetch(client: httpx.AsyncClient, url: str, max_bytes: int) -> tuple[str, bytes, str]:
    current = canonicalize_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlsplit(current)
        # Resolve immediately before each request. trust_env=False prevents a
        # deployment proxy from silently turning this into private-network egress.
        resolve_public_addresses(
            parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
        )
        response = await client.get(current)
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                raise CrawlPolicyError("redirect response had no location")
            current = canonicalize_url(urljoin(current, location))
            continue
        response.raise_for_status()
        data = response.content
        if len(data) > max_bytes:
            raise CrawlPolicyError("response exceeds the per-page byte limit")
        return canonicalize_url(current), data, response.headers.get("content-type", "")
    raise CrawlPolicyError("redirect limit exceeded")


async def crawl(spec: CrawlSpec) -> CrawlResult:
    frontier: deque[tuple[str, int]] = deque([(spec.seed_url, 0)])
    seen: set[str] = set()
    pages: list[CrawledPage] = []
    byte_limit = spec.max_downloaded_mb * 1024 * 1024
    downloaded = 0
    deadline = time.monotonic() + spec.max_crawl_minutes * 60
    capped = False
    async with httpx.AsyncClient(
        follow_redirects=False,
        cookies=None,
        trust_env=False,
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        while frontier:
            if len(pages) >= spec.max_pages or time.monotonic() >= deadline:
                capped = True
                break
            value, depth = frontier.popleft()
            if depth > spec.max_depth:
                continue
            try:
                canonical = canonicalize_url(value)
            except CrawlPolicyError:
                continue
            if canonical in seen or not spec.allows(canonical):
                continue
            seen.add(canonical)
            try:
                final, content, content_type = await _fetch(
                    client, canonical, byte_limit - downloaded
                )
                if not spec.allows(final):
                    raise CrawlPolicyError("redirect left the approved crawl scope")
                downloaded += len(content)
                if downloaded > byte_limit:
                    capped = True
                    break
                if not content_type.lower().startswith(("text/html", "application/xhtml+xml")):
                    pages.append(
                        CrawledPage(canonical, final, depth, None, error="Unsupported content type")
                    )
                    continue
                document = html_to_document(content, final)
                links = _Links()
                links.feed(content.decode("utf-8", errors="replace"))
                pages.append(CrawledPage(canonical, final, depth, document, noindex=links.noindex))
                if not links.nofollow and spec.scope != "page":
                    for href in links.links:
                        candidate = urljoin(final, href)
                        if spec.allows(candidate):
                            frontier.append((candidate, depth + 1))
            except (httpx.HTTPError, CrawlPolicyError, ValueError) as exc:
                pages.append(CrawledPage(canonical, canonical, depth, None, error=str(exc)))
    return CrawlResult(
        tuple(pages),
        complete=not capped,
        capped=capped,
        reason="safety limit reached" if capped else None,
    )
