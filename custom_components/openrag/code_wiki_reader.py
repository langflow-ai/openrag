"""Langflow custom component: read_wiki_page — exact fetch of one wiki page WITH evidence.

``search_wiki`` finds candidate pages; this tool fetches ONE page in full so the agent can quote it
and cite exact lines. It resolves a reference tiered like the COA reader:

1. a ``wiki_symbol_page`` by ``"repo_path :: Symbol"`` or by ``symbol`` alone,
2. a ``wiki_file_page`` / ``wiki_doc_page`` by ``repo_path``,
3. a ``wiki_module_page`` by ``module``,
4. the ``wiki_overview`` (``repo::<name>``),

then reassembles every chunk of that page (same ``repo_path`` [+``symbol``]) in ``chunk_index`` order —
lossless — and returns the full markdown, the parsed ``wiki_symbols`` (with exact line spans), the
resolved ``depends_on``/``called_by`` edges, and (for symbol pages) the raw ``wiki_source`` excerpt as
verbatim evidence. Provenance fields may live top-level (direct bulk ingest) or under ``metadata``
(OpenRAG callback), so ``_flatten`` merges both.

Exposed as a tool via ``to_toolkit`` (mark ``reference`` tool_mode). Takes NO embedding — it fetches by
identifier, not similarity. Wire ``read_wiki_page → Agent.tools``. Connection fields default to the
container's ``OPENSEARCH_*`` env vars.
"""

from __future__ import annotations

import json
import os

from lfx.custom.custom_component.component import Component
from lfx.io import BoolInput, DropdownInput, MessageTextInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data


def _env_fallback(value: str, *env_names: str, default: str = "") -> str:
    """Return ``value`` unless it is empty or just an env-var name; otherwise the first set env var,
    else ``default``."""
    v = (value or "").strip()
    if v and v not in env_names:
        return v
    for name in env_names:
        got = os.environ.get(name)
        if got:
            return got
    return default


class CodeWikiReader(Component):
    """Langflow tool that reads one indexed wiki page, or a symbol's source, in full."""

    display_name = "Code Wiki Reader"
    description = (
        "Read ONE wiki page in full by repo_path / 'repo_path :: Symbol' / module — lossless "
        "chunk reassembly, with line spans, edges, and raw source as evidence."
    )
    icon = "BookOpen"
    name = "CodeWikiReader"

    inputs = [
        MessageTextInput(
            name="reference",
            display_name="Page reference",
            tool_mode=True,
            info="Which wiki page to read. Accepts a repo_path (src/pkg/module.py), a symbol page "
            "('src/pkg/module.py :: ClassName.method' or just "
            "'ServiceRegistry.async_register'), a module path, or 'repo::<name>' for the overview. "
            "Use the repo_path/symbol returned by search_wiki.",
        ),
        StrInput(
            name="opensearch_url",
            display_name="OpenSearch URL",
            value="OPENSEARCH_URL",
            advanced=True,
            info="Falls back to env OPENSEARCH_URL / HOST:PORT.",
        ),
        StrInput(
            name="index_name",
            display_name="Index",
            value="OPENSEARCH_INDEX_NAME",
            advanced=True,
            info="Falls back to env OPENSEARCH_INDEX_NAME.",
        ),
        StrInput(name="username", display_name="Username", value="admin", advanced=True),
        SecretStrInput(
            name="password",
            display_name="Password",
            value="",
            advanced=True,
            info="Falls back to env OPENSEARCH_PASSWORD. Used when Auth Mode is 'basic'.",
        ),
        DropdownInput(
            name="auth_mode", display_name="Auth Mode", options=["basic", "jwt"], value="basic"
        ),
        SecretStrInput(
            name="jwt_token",
            display_name="JWT Token",
            value="",
            info="Falls back to env OPENSEARCH_JWT_TOKEN. Used when Auth Mode is 'jwt'.",
        ),
        StrInput(name="jwt_header", display_name="JWT Header", value="Authorization"),
        BoolInput(name="bearer_prefix", display_name="Bearer Prefix", value=False),
    ]

    outputs = [
        Output(
            display_name="Toolset", name="component_as_tool", method="to_toolkit", types=["Tool"]
        ),
        Output(display_name="Page", name="page_out", method="read_page"),
    ]

    # -- connection (mirrors search_wiki / the COA reader) ----------------
    def _resolve_url(self) -> str:
        """OpenSearch URL from the field, ``OPENSEARCH_URL``, or
        ``OPENSEARCH_HOST``/``OPENSEARCH_PORT``."""
        url = _env_fallback(self.opensearch_url, "OPENSEARCH_URL")
        if url:
            return url
        host = os.environ.get("OPENSEARCH_HOST", "opensearch")
        port = os.environ.get("OPENSEARCH_PORT", "9200")
        return f"https://{host}:{port}"

    def _index(self) -> str:
        """Index name from the field, ``OPENSEARCH_INDEX_NAME``, or ``documents``."""
        return _env_fallback(self.index_name, "OPENSEARCH_INDEX_NAME", default="documents")

    def _build_auth_kwargs(self) -> dict:
        """Keyword arguments for the OpenSearch client: a JWT header, or basic auth from the fields
        / env."""
        mode = (getattr(self, "auth_mode", "") or "basic").strip().lower()
        if mode == "jwt":
            token = (getattr(self, "jwt_token", "") or "").strip()
            if not token:
                token = os.environ.get("OPENSEARCH_JWT_TOKEN", "")
            if not token:
                raise ValueError("Auth Mode is 'jwt' but no jwt_token was provided.")
            header_name = (getattr(self, "jwt_header", "") or "Authorization").strip()
            header_value = f"Bearer {token}" if getattr(self, "bearer_prefix", False) else token
            return {"headers": {header_name: header_value}}
        return {
            "http_auth": (
                _env_fallback(self.username, "OPENSEARCH_USERNAME", default="admin"),
                _env_fallback(self.password, "OPENSEARCH_PASSWORD"),
            )
        }

    def _client(self):
        """OpenSearch client for this component's connection settings."""
        from opensearchpy import OpenSearch

        url = self._resolve_url()
        return OpenSearch(
            hosts=[url],
            use_ssl=url.startswith("https"),
            verify_certs=False,
            ssl_show_warn=False,
            timeout=30,
            **self._build_auth_kwargs(),
        )

    @staticmethod
    def _term_any(field: str, value) -> dict:
        """Exact match on `field` whether it is indexed top-level (direct bulk write) or nested
        under `metadata` (OpenRAG ingest callback — Knowledge-UI uploads). Dynamic mapping gives
        metadata strings a `.keyword` subfield; a term on a missing field just matches nothing."""
        op = "terms" if isinstance(value, list) else "term"
        return {
            "bool": {
                "should": [
                    {op: {f: value}}
                    for f in (
                        field,
                        f"{field}.keyword",
                        f"metadata.{field}",
                        f"metadata.{field}.keyword",
                    )
                ],
                "minimum_should_match": 1,
            }
        }

    @staticmethod
    def _flatten(source: dict) -> dict:
        """Copy of a hit's ``_source`` with ``metadata.*`` fields (and frontmatter fallbacks) lifted
        to the top level."""
        flat = dict(source)
        meta = source.get("metadata")
        if isinstance(meta, dict):
            for k, v in meta.items():
                if not flat.get(k):
                    flat[k] = v
        # Fallback: extract provenance fields from YAML frontmatter in text
        if not flat.get("repo_path"):
            import re

            text = flat.get("text") or ""
            fm_match = re.search(r"---\n(.*?)\n---", text, re.DOTALL)
            if fm_match:
                for line in fm_match.group(1).splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        k = k.strip()
                        v = v.strip().strip('"')
                        if k and v and not flat.get(k):
                            flat[k] = v
            if not flat.get("repo_path"):
                hdr = re.match(r"#\s+\[([^\]]+)\]", text)
                if hdr:
                    flat["repo_path"] = hdr.group(1)
        return flat

    # -- resolution -------------------------------------------------------
    _EXCLUDE = {
        "excludes": ["chunk_embedding*", "vector_field", "vector", "metadata.chunk_embedding*"]
    }

    def _search(self, should: list[dict], size: int = 1) -> list[dict]:
        """Run a bool/should query and return the flattened ``_source`` of up to ``size`` hits."""
        body = {
            "size": size,
            "query": {"bool": {"should": should, "minimum_should_match": 1}},
            "_source": self._EXCLUDE,
        }
        hits = self._client().search(index=self._index(), body=body).get("hits", {}).get("hits", [])
        return [self._flatten(h.get("_source", {})) for h in hits]

    def _resolve(self, raw: str) -> dict | None:
        """Find ONE page's identity (repo_path [+symbol]) by tiered matching. Returns a chunk source."""
        # "repo_path :: Symbol" form → pin both.
        symbol = ""
        repo_path = raw
        # The repo overview page is stored as "repo::<name>"; its "::" is part of the path.
        for sep in () if raw.startswith("repo::") else ("::", " :: ", "#"):
            if sep in raw:
                left, right = raw.split(sep, 1)
                repo_path, symbol = left.strip(), right.strip()
                break

        # Tier 1 — repo_path + symbol (a specific symbol page).
        if symbol:
            tier1 = [
                {
                    "bool": {
                        "must": [
                            self._term_any("repo_path", repo_path),
                            self._term_any("symbol", symbol),
                        ]
                    }
                }
            ]
            hits = self._search(tier1)
            if hits:
                return hits[0]

        # Tier 2 — exact repo_path (prefer the file/doc page = chunk_index 0 of a non-symbol page).
        tier2 = [self._term_any("repo_path", repo_path)]
        hits = self._search(tier2, size=50)
        if hits:
            # Prefer the page WITHOUT a symbol (the file/module/overview page) if present.
            non_sym = [h for h in hits if not (h.get("symbol") or "").strip()]
            return (non_sym or hits)[0]

        # Tier 3 — bare symbol name across the repo.
        if not symbol:
            symbol = raw
        tier3 = [self._term_any("symbol", symbol)]
        hits = self._search(tier3)
        if hits:
            return hits[0]

        # Tier 4 — module page, then fuzzy title/filename.
        tier4 = [
            self._term_any("module", raw),
            {"match": {"filename": raw}},
            {"match": {"title": raw}},
            {"match": {"metadata.title": raw}},
            {"match": {"text": raw}},
        ]
        hits = self._search(tier4)
        return hits[0] if hits else None

    def _fetch_chunks(self, repo_path: str, symbol: str) -> list[dict]:
        """All chunks of ONE page (same repo_path + symbol), sorted by chunk_index — lossless."""
        must: list[dict] = [self._term_any("repo_path", repo_path)]
        # symbol pages share a repo_path with the file page; pin the symbol (or its absence).
        if symbol:
            must.append(self._term_any("symbol", symbol))
        # Drop the symbol pages in the query: they share the file page's repo_path and could
        # otherwise fill the 500-hit window before the file page's own chunks are returned.
        must_not = [] if symbol else [self._term_any("content_kind", "wiki_symbol_page")]
        body = {
            "size": 500,
            "query": {"bool": {"must": must, "must_not": must_not}},
            "_source": self._EXCLUDE,
        }
        hits = self._client().search(index=self._index(), body=body).get("hits", {}).get("hits", [])
        sources = [self._flatten(h.get("_source", {})) for h in hits]
        if not symbol:  # keep only the non-symbol page's chunks (file/module/overview)
            sources = [s for s in sources if not (s.get("symbol") or "").strip()]
        sources.sort(key=lambda c: int(c.get("chunk_index") or 0))
        return sources

    @staticmethod
    def _parse(field: str, meta: dict):
        """Decode a JSON-encoded list field; ``[]`` if it is missing or malformed."""
        try:
            return json.loads(meta.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def read_page(self) -> list[Data]:
        """Resolve the reference to a page and return its reassembled text with provenance."""
        raw = (self.reference or "").strip().strip("[]{}() \t\n\r`\"'")
        if not raw:
            return [
                Data(
                    data={
                        "filename": raw,
                        "text": "No page reference provided. Use search_wiki to find one.",
                        "score": 0,
                    }
                )
            ]

        try:
            s = self._resolve(raw)
        except Exception as e:  # noqa: BLE001
            return [
                Data(data={"filename": raw, "text": f"OpenSearch query failed: {e}", "score": 0})
            ]
        if s is None:
            return [
                Data(
                    data={
                        "filename": raw,
                        "text": f"No wiki page found for '{raw}'. Try search_wiki to locate it.",
                        "score": 0,
                    }
                )
            ]

        repo_path = s.get("repo_path", "")
        symbol = (s.get("symbol") or "").strip()
        try:
            chunks = self._fetch_chunks(repo_path, symbol) if repo_path else []
        except Exception:  # noqa: BLE001 - fall back to the single resolved hit
            chunks = []
        if chunks:
            meta = next((c for c in chunks if int(c.get("chunk_index") or 0) == 0), chunks[0])
            full_md = "".join(c.get("wiki_markdown") or "" for c in chunks)
            n_chunks = len(chunks)
        else:
            meta = s
            full_md = s.get("wiki_markdown") or s.get("text") or ""
            n_chunks = 1

        label = repo_path + (f" :: {symbol}" if symbol else "")
        self.status = (
            f"read_wiki_page('{raw[:40]}') → {label} "
            f"({meta.get('content_kind', '')}, {n_chunks} chunk(s))"
        )
        return [
            Data(
                data={
                    # Stock UI fields
                    "filename": label,
                    "text": full_md,
                    "score": 0,
                    "page": None,
                    "source_url": meta.get("source_url", meta.get("repo_url", "")),
                    # Provenance extras
                    "repo_path": meta.get("repo_path", ""),
                    "content_kind": meta.get("content_kind", ""),
                    "symbol": meta.get("symbol", ""),
                    "language": meta.get("language", ""),
                    "module": meta.get("module", ""),
                    "summary": meta.get("wiki_summary", ""),
                    "line_start": meta.get("line_start"),
                    "line_end": meta.get("line_end"),
                    "symbols": self._parse("wiki_symbols", meta),
                    "depends_on": self._parse("wiki_depends_on", meta),
                    "called_by": self._parse("wiki_called_by", meta),
                    "files": self._parse("wiki_files", meta),
                    "repo_url": meta.get("repo_url", ""),
                    "repo_ref": meta.get("repo_ref", ""),
                    "source": meta.get("wiki_source", ""),
                }
            )
        ]

    async def to_toolkit(self):
        """Expose this component's tool-mode inputs as agent tools."""
        from lfx.base.tools.component_tool import ComponentToolkit

        return ComponentToolkit(component=self).get_tools()
