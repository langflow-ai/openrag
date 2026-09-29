"""Inert HTML-to-Markdown conversion for public pages."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            self.skip += 1
        elif not self.skip and tag in {
            "p",
            "div",
            "section",
            "article",
            "li",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
        }:
            self.parts.append("\n\n" if tag != "li" else "\n- ")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = re.sub(r"\s+", " ", unescape(data)).strip()
            if text:
                self.parts.append(text + " ")


@dataclass(frozen=True)
class WebDocument:
    title: str
    markdown: str
    content_hash: str
    byte_size: int


def html_to_document(content: bytes, source_url: str) -> WebDocument:
    raw = content.decode("utf-8", errors="replace")
    title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", raw, re.I | re.S)
    title = (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(title_match.group(1)))).strip()
        if title_match
        else source_url
    )
    body = re.sub(r"<head[^>]*>.*?</head\s*>", "", raw, flags=re.I | re.S)
    parser = _Parser()
    parser.feed(body)
    text = re.sub(r"\n{3,}", "\n\n", "".join(parser.parts)).strip()
    if not text:
        raise ValueError("HTML document produced no extractable text")
    markdown = f"# {title}\n\n{text}\n".replace("\x00", "")
    normalized = re.sub(r"\s+", " ", markdown).strip()
    return WebDocument(
        title=title[:512],
        markdown=markdown,
        content_hash=hashlib.sha256(normalized.encode()).hexdigest(),
        byte_size=len(content),
    )
