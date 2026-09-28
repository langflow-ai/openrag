"""Smoke coverage for the isolated Scrapy runner contract."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from scrapy import Request
from scrapy.http import Response

from connectors.url import scrapy_runner
from connectors.url.policy import CrawlSpec
from connectors.url.scrapy_runner import ManagedWebsiteSpider, ValidatedAddressResolver


def test_scrapy_runner_writes_a_manifest_when_policy_rejects_the_seed(tmp_path):
    """The parent adapter always receives a result, even for blocked URLs.

    ``localhost`` is deliberately rejected by the public-network policy, so
    this exercises the real Scrapy lifecycle without making an external request.
    """
    source_root = Path(__file__).resolve().parents[2] / "src"
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            value for value in (str(source_root), os.environ.get("PYTHONPATH")) if value
        ),
    }
    result = subprocess.run(
        [sys.executable, "-m", "connectors.url.scrapy_runner", "--output-dir", str(tmp_path)],
        input=json.dumps({"seed_url": "http://localhost/"}),
        text=True,
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads((tmp_path / "result.json").read_text())
    assert manifest["complete"] is False
    assert manifest["capped"] is False
    assert manifest["pages"], manifest
    assert manifest["pages"][0]["error"]


def test_non_text_html_response_is_recorded_without_extracting_links(tmp_path):
    spider = ManagedWebsiteSpider(
        spec={"seed_url": "https://docs.example.com/"},
        output_dir=str(tmp_path),
    )
    spider._links = MagicMock()
    response = Response(
        "https://docs.example.com/",
        status=200,
        headers={b"Content-Type": b"text/html"},
        body=b"<html><body>Documentation</body></html>",
        request=Request(
            "https://docs.example.com/",
            meta={"canonical_url": "https://docs.example.com/", "crawl_depth": 0},
        ),
    )

    assert list(spider.parse_page(response)) == []
    spider._links.extract_links.assert_not_called()
    assert spider.pages[0]["canonical_url"] == "https://docs.example.com/"


def test_validated_resolver_uses_the_public_address_from_policy_validation(monkeypatch):
    scrapy_runner._validated_public_addresses.clear()
    monkeypatch.setattr(scrapy_runner, "resolve_public_addresses", lambda *_args: ("8.8.8.8",))
    spider = MagicMock(spec=ManagedWebsiteSpider)
    spider.spec = CrawlSpec(seed_url="https://docs.example.com/")
    scrapy_runner.CrawlPolicyDownloaderMiddleware().process_request(
        Request("https://docs.example.com/"), spider
    )
    monkeypatch.setattr(
        scrapy_runner.CachingThreadedResolver,
        "getHostByName",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a rebinding lookup to a private address was attempted")
        ),
    )

    resolver = object.__new__(ValidatedAddressResolver)
    values: list[str] = []
    resolver.getHostByName("docs.example.com").addCallback(values.append)

    assert values == ["8.8.8.8"]


def test_aggregate_limit_counts_error_and_redirect_response_bodies(tmp_path):
    spider = ManagedWebsiteSpider(
        spec={"seed_url": "https://docs.example.com/", "max_downloaded_mb": 1},
        output_dir=str(tmp_path),
    )
    spider.crawler = MagicMock()
    error_response = Response("https://docs.example.com/error", status=503, body=b"x" * 600_000)
    redirect_response = Response(
        "https://docs.example.com/redirect", status=302, body=b"x" * 500_000
    )

    assert spider.count_downloaded_response(error_response) is True
    assert spider.count_downloaded_response(redirect_response) is False
    assert spider.downloaded_bytes == 1_100_000
    assert spider.capped is True
    spider.crawler.engine.close_spider.assert_called_once()
