"""Langflow custom component: search_wiki — hybrid wiki search that KEEPS provenance.

The stock OpenSearch tool pins search ``_source`` to a fixed 13-field allow-list
(``filename, mimetype, page, text, source_url, owner, embedding_model, parser, chunk_size,
chunk_overlap, allowed_users, allowed_groups, allowed_principals``) — it DROPS ``repo_path``,
``wiki_symbols``, line spans and the resolved edges. For a cite-the-evidence code wiki that is fatal,
so this tool reuses the SAME hybrid query (KNN ``boost 0.7`` + keyword ``text^2/filename^1.5``
``boost 0.3``, ``minimum_should_match 1``) but returns the FULL ``_source`` (minus embedding vectors)
so every hit carries its provenance.

Exposed to the agent as a tool via ``to_toolkit`` (mark ``query`` tool_mode). Wire the
embedding model into ``embedding`` (same model used at ingest) and ``search_wiki → Agent.tools``.
Connection fields default to the container's ``OPENSEARCH_*`` env vars.
"""

from __future__ import annotations

import json
import os

from lfx.custom.custom_component.component import Component
from lfx.io import (
    BoolInput,
    DropdownInput,
    HandleInput,
    IntInput,
    MessageTextInput,
    Output,
    SecretStrInput,
    StrInput,
)
from lfx.schema.data import Data


def _env_fallback(value: str, *env_names: str, default: str = "") -> str:
    v = (value or "").strip()
    if v and v not in env_names:
        return v
    for name in env_names:
        got = os.environ.get(name)
        if got:
            return got
    return default


class CodeWikiSearch(Component):
    display_name = "Code Wiki Search"
    description = (
        "Hybrid search over the code wiki that KEEPS provenance (repo_path, symbols, line spans)."
    )
    icon = "Search"
    name = "CodeWikiSearch"

    inputs = [
        MessageTextInput(
            name="query",
            display_name="Query",
            tool_mode=True,
            info="What to find in the code wiki, e.g. 'how do I register a service'. Returns matching "
            "wiki pages WITH repo_path, summary, and symbol line spans for citation.",
        ),
        HandleInput(
            name="embedding",
            display_name="Embedding",
            input_types=["Embeddings"],
            info="Embeddings for the query vector — MUST be the same model used at ingest "
            "(the embedding model of the target index).",
        ),
        IntInput(
            name="top_k", display_name="Results", value=6, info="How many wiki pages to return."
        ),
        MessageTextInput(
            name="content_kind",
            display_name="Restrict to kind",
            value="",
            advanced=True,
            tool_mode=True,
            info="Optional filter: wiki_overview | wiki_module_page | wiki_file_page | "
            "wiki_symbol_page | wiki_doc_page. Empty = all.",
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
        SecretStrInput(name="jwt_token", display_name="JWT Token", value=""),
        StrInput(name="jwt_header", display_name="JWT Header", value="Authorization"),
        BoolInput(name="bearer_prefix", display_name="Bearer Prefix", value=False),
    ]

    outputs = [
        Output(
            display_name="Toolset", name="component_as_tool", method="to_toolkit", types=["Tool"]
        ),
        Output(display_name="Results", name="search_out", method="search", types=["Data"]),
    ]

    # -- connection (mirrors the multimodal OpenSearch + COA reader) ------
    def _resolve_url(self) -> str:
        url = _env_fallback(self.opensearch_url, "OPENSEARCH_URL")
        if url:
            return url
        host = os.environ.get("OPENSEARCH_HOST", "opensearch")
        port = os.environ.get("OPENSEARCH_PORT", "9200")
        return f"https://{host}:{port}"

    def _index(self) -> str:
        return _env_fallback(self.index_name, "OPENSEARCH_INDEX_NAME", default="documents")

    def _build_auth_kwargs(self) -> dict:
        mode = (getattr(self, "auth_mode", "") or "basic").strip().lower()
        if mode == "jwt":
            token = (getattr(self, "jwt_token", "") or "").strip()
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

    def _knn_fields(self, client, query_vec: list) -> list[str]:
        """Discover knn_vector fields whose dimension matches the query vector."""
        try:
            mapping = client.indices.get_mapping(index=self._index())
        except Exception:  # noqa: BLE001
            return []
        query_dim = len(query_vec)
        fields: set[str] = set()
        for idx in mapping.values():
            props = (idx.get("mappings") or {}).get("properties") or {}
            for name, spec in props.items():
                if (
                    name.startswith("chunk_embedding")
                    and isinstance(spec, dict)
                    and spec.get("type") == "knn_vector"
                    and spec.get("dimension") == query_dim
                ):
                    fields.add(name)
        return sorted(fields)

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
        """Provenance fields live top-level (direct bulk ingest) OR under `metadata` (OpenRAG callback).
        Merge so downstream reads one flat dict either way.
        Fallback: parse YAML frontmatter from `text` when repo_path/content_kind are absent
        (doc-wiki flow stores these fields only inside the text body, not as indexed fields)."""
        flat = dict(source)
        meta = source.get("metadata")
        if isinstance(meta, dict):
            for k, v in meta.items():
                if not flat.get(k):  # prefer metadata value over empty top-level
                    flat[k] = v
        # Fallback: extract provenance fields from YAML frontmatter in text
        if not flat.get("repo_path"):
            text = flat.get("text") or ""
            # Format: "# [repo_path] ...\n---\nkey: value\n...\n---\n"
            import re

            fm_match = re.search(r"---\n(.*?)\n---", text, re.DOTALL)
            if fm_match:
                for line in fm_match.group(1).splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        k = k.strip()
                        v = v.strip().strip('"')
                        if k and v and not flat.get(k):
                            flat[k] = v
            # Also try header line: "# [repo_path] ..."
            if not flat.get("repo_path"):
                hdr = re.match(r"#\s+\[([^\]]+)\]", text)
                if hdr:
                    flat["repo_path"] = hdr.group(1)
        return flat

    def search(self) -> Data:
        q = (self.query or "").strip()
        if not q:
            return Data(data={"error": "Empty query.", "results": []})
        try:
            vec = self.embedding.embed_query(q)
        except Exception as e:  # noqa: BLE001
            return Data(data={"error": f"Embedding failed: {e}", "results": []})

        client = self._client()
        limit = int(getattr(self, "top_k", 6) or 6)
        knn_fields = self._knn_fields(client, vec)
        knn_queries = [{"knn": {f: {"vector": vec, "k": max(limit, 10)}}} for f in knn_fields]

        filters: list[dict] = []
        kind = (getattr(self, "content_kind", "") or "").strip()
        if kind:
            filters.append(self._term_any("content_kind", kind))

        should: list[dict] = []
        if knn_queries:
            should.append({"dis_max": {"tie_breaker": 0.0, "boost": 0.7, "queries": knn_queries}})
        should.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["text^2", "filename^1.5"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                    "boost": 0.3,
                }
            }
        )

        body = {
            "query": {
                "bool": {"should": should, "minimum_should_match": 1, "filter": filters}
                if should
                else {"match_all": {}}
            },
            "_source": {
                "excludes": [
                    "chunk_embedding*",
                    "vector_field",
                    "vector",
                    "metadata.chunk_embedding*",
                ]
            },
            "size": limit,
        }
        try:
            resp = client.search(index=self._index(), body=body)
        except Exception as e:  # noqa: BLE001
            return Data(data={"error": f"OpenSearch query failed: {e}", "results": []})

        results = []
        for hit in resp.get("hits", {}).get("hits", []):
            s = self._flatten(hit.get("_source", {}))
            try:
                symbols = json.loads(s.get("wiki_symbols") or "[]")
            except (json.JSONDecodeError, TypeError):
                symbols = []
            snippet = (s.get("text") or "")[:600]
            results.append(
                Data(
                    data={
                        # Stock UI fields — filename + text + score make the UI render "Found N results"
                        "filename": s.get("repo_path") or s.get("filename", ""),
                        "text": snippet,
                        "score": hit.get("_score"),
                        "page": None,
                        "source_url": (s.get("metadata") or {}).get("source_url")
                        or s.get("source_url", ""),
                        # Provenance extras
                        "repo_path": s.get("repo_path", ""),
                        "content_kind": s.get("content_kind", ""),
                        "symbol": s.get("symbol", ""),
                        "language": s.get("language", ""),
                        "module": s.get("module", ""),
                        "summary": s.get("wiki_summary", ""),
                        "symbols": symbols,
                        "line_start": s.get("line_start"),
                        "line_end": s.get("line_end"),
                    }
                )
            )
        self.status = f"search_wiki('{q[:40]}') → {len(results)} hit(s)"
        return results

    async def to_toolkit(self):
        from lfx.base.tools.component_tool import ComponentToolkit

        return ComponentToolkit(component=self).get_tools()
