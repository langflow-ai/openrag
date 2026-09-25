"""Isolated Scrapy runner for a single managed URL source crawl.

This module is intentionally executed as a subprocess by ``crawler.py``. It
keeps Twisted out of the FastAPI process while retaining the existing host-side
scope and public-network policy for every request and redirect.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import scrapy
from scrapy import Request
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import IgnoreRequest
from scrapy.linkextractors import LinkExtractor

from .policy import (
    CrawlPolicyError,
    CrawlSpec,
    canonicalize_url,
    normalize_host,
    resolve_public_addresses,
)

USER_AGENT = "OpenRAG URL connector (+https://openrag.ai)"


class CrawlPolicyDownloaderMiddleware:
    """Reject private, out-of-scope, or redirected requests before download."""

    def process_request(self, request: Request, spider: ManagedWebsiteSpider) -> None:
        try:
            url = canonicalize_url(request.url)
            if not spider.allows_request(
                url, is_robots=request.meta.get("dont_obey_robotstxt", False)
            ):
                raise CrawlPolicyError("URL is not within the allowed crawl scope")
            parsed = urlsplit(url)
            resolve_public_addresses(
                parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
            )
        except CrawlPolicyError as exc:
            raise IgnoreRequest(str(exc)) from exc

    def process_exception(
        self,
        request: Request,
        exception: Exception,
        spider: ManagedWebsiteSpider,
    ) -> None:
        """Persist request rejections that Scrapy otherwise drops silently.

        Both this middleware and Scrapy's robots middleware use ``IgnoreRequest``.
        Those failures bypass a request errback, so record the source request here
        to preserve the actual failure reason for the task and source projection.
        """
        if request.meta.get("dont_obey_robotstxt", False):
            return
        if isinstance(exception, IgnoreRequest):
            spider.request_rejected(request, str(exception))


class ManagedWebsiteSpider(scrapy.Spider):
    name = "openrag_managed_website"

    def __init__(self, *, spec: dict[str, Any], output_dir: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.spec = CrawlSpec(**spec)
        self.output_dir = Path(output_dir)
        self.pages: list[dict[str, Any]] = []
        self._recorded: set[str] = set()
        self._scheduled: set[str] = set()
        self.downloaded_bytes = 0
        self.capped = False
        self.reason: str | None = None
        self._links = LinkExtractor(tags=("a",), attrs=("href",), canonicalize=False)

    def allows_request(self, url: str, *, is_robots: bool) -> bool:
        if self.spec.allows(url):
            return True
        if not is_robots or urlsplit(url).path != "/robots.txt":
            return False
        host = normalize_host(urlsplit(url).hostname or "")
        seed_host = normalize_host(urlsplit(self.spec.seed_url).hostname or "")
        return (
            host == seed_host
            or host in self.spec.additional_hosts
            or (self.spec.allow_subdomains and host.endswith("." + seed_host))
        )

    def _stop_for_limit(self, reason: str) -> None:
        self.capped = True
        self.reason = "safety limit reached"
        self.crawler.engine.close_spider(self, reason)

    def _record(
        self,
        canonical_url: str,
        final_url: str,
        depth: int,
        *,
        noindex: bool = False,
        error: str | None = None,
        content: bytes | None = None,
    ) -> None:
        if canonical_url in self._recorded:
            return
        self._recorded.add(canonical_url)
        record: dict[str, Any] = {
            "canonical_url": canonical_url,
            "final_url": final_url,
            "depth": depth,
            "noindex": noindex,
            "error": error,
        }
        if content is not None:
            pages_dir = self.output_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            relative_path = Path("pages") / f"{len(self.pages):06d}.html"
            (self.output_dir / relative_path).write_bytes(content)
            record["content_path"] = str(relative_path)
        self.pages.append(record)

    def request_rejected(self, request: Request, error: str) -> None:
        canonical_url = str(request.meta.get("canonical_url", request.url))
        depth = int(request.meta.get("crawl_depth", 0))
        self._record(canonical_url, canonical_url, depth, error=error)

    def _request(self, value: str, depth: int) -> Request | None:
        if depth > self.spec.max_depth:
            return None
        try:
            canonical_url = canonicalize_url(value)
        except CrawlPolicyError:
            return None
        if canonical_url in self._scheduled or not self.spec.allows(canonical_url):
            return None
        self._scheduled.add(canonical_url)
        return Request(
            canonical_url,
            callback=self.parse_page,
            errback=self.request_failed,
            dont_filter=True,
            meta={"canonical_url": canonical_url, "crawl_depth": depth},
        )

    async def start(self):
        request = self._request(self.spec.seed_url, 0)
        if request is not None:
            yield request

    def parse_page(self, response: scrapy.http.Response):
        canonical_url = str(response.meta["canonical_url"])
        depth = int(response.meta["crawl_depth"])
        try:
            final_url = canonicalize_url(response.url)
        except CrawlPolicyError as exc:
            self._record(canonical_url, canonical_url, depth, error=str(exc))
            return
        if not self.spec.allows(final_url):
            self._record(
                canonical_url, final_url, depth, error="redirect left the approved crawl scope"
            )
            return
        if len(self._recorded) >= self.spec.max_pages:
            self._stop_for_limit("openrag_page_limit")
            return

        content_type = response.headers.get(b"Content-Type", b"").decode("latin1").lower()
        if not 200 <= response.status < 300:
            self._record(canonical_url, final_url, depth, error=f"HTTP {response.status}")
            return
        if not content_type.startswith(("text/html", "application/xhtml+xml")):
            self._record(canonical_url, final_url, depth, error="Unsupported content type")
            return
        if self.downloaded_bytes + len(response.body) > self.spec.max_downloaded_mb * 1024 * 1024:
            self._record(
                canonical_url, final_url, depth, error="response exceeds the download limit"
            )
            self._stop_for_limit("openrag_download_limit")
            return

        self.downloaded_bytes += len(response.body)
        if not isinstance(response, scrapy.http.TextResponse):
            self._record(canonical_url, final_url, depth, content=response.body)
            return

        robots = " ".join(
            response.xpath(
                "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                "'abcdefghijklmnopqrstuvwxyz')='robots']/@content"
            ).getall()
        ).lower()
        noindex, nofollow = "noindex" in robots, "nofollow" in robots
        self._record(
            canonical_url,
            final_url,
            depth,
            noindex=noindex,
            content=response.body,
        )

        if nofollow or self.spec.scope == "page":
            return
        requests = [
            request
            for link in self._links.extract_links(response)
            if (request := self._request(link.url, depth + 1)) is not None
        ]
        if len(self._recorded) >= self.spec.max_pages:
            if requests:
                self._stop_for_limit("openrag_page_limit")
            return
        yield from requests

    def request_failed(self, failure: Any) -> None:
        request = failure.request
        if request.meta.get("dont_obey_robotstxt", False):
            return
        self.request_rejected(request, failure.getErrorMessage())

    def closed(self, reason: str) -> None:
        if reason in {"closespider_timeout", "openrag_page_limit", "openrag_download_limit"}:
            self.capped = True
            self.reason = "safety limit reached"
        manifest = {
            "pages": self.pages,
            "complete": not self.capped,
            "capped": self.capped,
            "reason": self.reason,
        }
        temporary = self.output_dir / "result.tmp"
        temporary.write_text(json.dumps(manifest), encoding="utf-8")
        temporary.replace(self.output_dir / "result.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    spec = CrawlSpec(**json.loads(sys.stdin.read())).as_dict()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(spec["max_downloaded_mb"]) * 1024 * 1024
    settings = {
        "BOT_NAME": "openrag_url_connector",
        "COOKIES_ENABLED": False,
        "CLOSESPIDER_TIMEOUT": int(spec["max_crawl_minutes"]) * 60,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DEPTH_LIMIT": int(spec["max_depth"]),
        "DOWNLOAD_MAXSIZE": max_bytes,
        "DOWNLOAD_TIMEOUT": 20,
        "HTTPERROR_ALLOW_ALL": True,
        "HTTPPROXY_ENABLED": False,
        "LOG_ENABLED": False,
        "REDIRECT_MAX_TIMES": 5,
        "RETRY_ENABLED": False,
        "ROBOTSTXT_OBEY": True,
        "TELNETCONSOLE_ENABLED": False,
        "USER_AGENT": USER_AGENT,
        "DOWNLOADER_MIDDLEWARES": {
            "connectors.url.scrapy_runner.CrawlPolicyDownloaderMiddleware": 50,
        },
    }
    process = CrawlerProcess(settings=settings)
    process.crawl(ManagedWebsiteSpider, spec=spec, output_dir=str(output_dir))
    process.start(stop_after_crawl=True)


if __name__ == "__main__":
    main()
