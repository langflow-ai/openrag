"""Fetch a URL, strip HTML, and write the visible text to a temporary file.

Used by the default-docs ingestion flow when DEFAULT_DOCS_INGEST_SOURCE=url
and the OpenRAG (non-Langflow) ingestion path is active.
"""

import html
import re
import tempfile
from html.parser import HTMLParser

import httpx


class _VisibleTextHTMLParser(HTMLParser):
    """Extract visible text while skipping script/style content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth == 0 and data and not data.isspace():
            self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(self._chunks)


async def materialize_url_as_text_file(docs_url: str, crawl_depth: int) -> str:
    """Fetch URL content and write a temporary text file for OpenRAG ingestion."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(docs_url)
        response.raise_for_status()
        raw_html = response.text

    title_match = re.search(
        r"<title[^>]*>(.*?)</title\s*>",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = html.unescape(title_match.group(1).strip()) if title_match else "OpenRAG"

    text_parser = _VisibleTextHTMLParser()
    text_parser.feed(raw_html)
    text_parser.close()
    normalized_text = re.sub(r"\s+", " ", text_parser.get_text()).strip()

    content = (
        f"{title}\n\nSource URL: {docs_url}\nCrawl depth: {crawl_depth}\n\n{normalized_text}\n"
    )

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="openrag-url-default-",
        delete=False,
        encoding="utf-8",
    )
    with temp_file:
        temp_file.write(content)
    return temp_file.name
