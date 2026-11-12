"""Langflow custom component: walk_dependencies — real multi-hop code reasoning over resolved edges.

The wiki stores RESOLVED dependency edges on every file/symbol page (``wiki_depends_on`` /
``wiki_called_by`` = actual ``repo_path``s, not fuzzy strings). Given a ``repo_path``, this tool returns
the neighbours in the import graph — what it depends on and what depends on it — each with the
neighbour's one-line ``wiki_summary`` and the line spans of its top-level symbols, so the agent can
answer questions like "what calls ``async_register`` and where's the wrapper?" by walking the graph
instead of re-searching. Optionally follows N hops (bounded) for transitive reachability.

Provenance fields may live top-level (direct bulk ingest) or under ``metadata`` (OpenRAG callback);
``_flatten`` merges both. Returns a list of Data (origin + one per neighbour), each with
``filename``/``text`` so OpenRAG's chat UI renders them. Exposed as a tool via ``to_toolkit`` (mark ``repo_path`` tool_mode). Takes NO
embedding. Wire ``walk_dependencies → Agent.tools``. Connection fields default to ``OPENSEARCH_*`` env.
"""

from __future__ import annotations

import json
import os

from lfx.custom.custom_component.component import Component
from lfx.io import (
    BoolInput,
    DropdownInput,
    IntInput,
    MessageTextInput,
    Output,
    SecretStrInput,
    StrInput,
)
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


class CodeWikiDeps(Component):
    """Langflow tool that walks the import graph of an indexed repo from a file."""

    display_name = "Code Wiki Dependencies"
    description = (
        "Walk the resolved import graph from a repo_path: return depends_on / called_by "
        "neighbours with their summaries and symbol line spans (bounded multi-hop)."
    )
    icon = "Share2"
    name = "CodeWikiDeps"

    inputs = [
        MessageTextInput(
            name="repo_path",
            display_name="Repo path",
            tool_mode=True,
            info="The file to walk from, e.g. 'src/pkg/module.py'. Returns what it depends on and "
            "what depends on it (use the repo_path from search_wiki / read_wiki_page).",
        ),
        DropdownInput(
            name="direction",
            display_name="Direction",
            tool_mode=True,
            options=["both", "depends_on", "called_by"],
            value="both",
            advanced=True,
            info="both = neighbours in either direction; depends_on = imports; "
            "called_by = importers.",
        ),
        IntInput(
            name="hops",
            display_name="Hops",
            value=1,
            advanced=True,
            info="How many edges to follow transitively (1 = direct neighbours). Bounded to 3.",
        ),
        IntInput(
            name="max_nodes",
            display_name="Max neighbours",
            value=40,
            advanced=True,
            info="Cap on neighbours returned (guardrail for hub files).",
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
        Output(display_name="Neighbours", name="deps_out", method="walk", types=["Data"]),
    ]

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

    @staticmethod
    def _parse(field: str, meta: dict):
        """Decode a JSON-encoded list field; ``[]`` if it is missing or malformed."""
        try:
            return json.loads(meta.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def _fetch_file_page(self, client, repo_path: str) -> dict | None:
        """Fetch the file page (chunk 0, no symbol) for a repo_path — carries the edges + summary."""
        body = {
            "size": 20,
            "query": {
                "bool": {
                    "must": [self._term_any("repo_path", repo_path)],
                    "filter": [
                        self._term_any(
                            "content_kind", ["wiki_file_page", "wiki_doc_page", "wiki_module_page"]
                        )
                    ],
                }
            },
            "_source": [
                "repo_path",
                "content_kind",
                "language",
                "module",
                "wiki_summary",
                "wiki_symbols",
                "wiki_depends_on",
                "wiki_called_by",
                "chunk_index",
                "metadata.*",
                "text",
            ],
        }
        hits = client.search(index=self._index(), body=body).get("hits", {}).get("hits", [])
        sources = [self._flatten(h.get("_source", {})) for h in hits]
        if not sources:
            return None
        sources.sort(key=lambda c: int(c.get("chunk_index") or 0))
        return sources[0]

    def _node_summary(self, client, repo_path: str) -> dict:
        """Summary of one graph node (language, module, summary, symbols), or ``found: False``;
        never raises."""
        try:
            page = self._fetch_file_page(client, repo_path)
        except Exception:  # noqa: BLE001 - one unreachable neighbour must not drop the traversal
            page = None
        if not page:
            return {"repo_path": repo_path, "found": False}
        syms = self._parse("wiki_symbols", page)
        return {
            "repo_path": repo_path,
            "found": True,
            "content_kind": page.get("content_kind", ""),
            "language": page.get("language", ""),
            "module": page.get("module", ""),
            "summary": page.get("wiki_summary", ""),
            "symbols": [
                {
                    "symbol": s.get("symbol"),
                    "kind": s.get("kind"),
                    "line_start": s.get("line_start"),
                    "line_end": s.get("line_end"),
                }
                for s in syms
            ],
        }

    @staticmethod
    def _fmt_paths(paths: list[str]) -> str:
        """Comma-separated paths, or ``(none)``."""
        return ", ".join(paths) if paths else "(none)"

    def walk(self) -> list[Data]:
        """Return one Data per graph node: the origin first, then each neighbour.

        Every item carries ``filename`` + ``text`` (in addition to the structured fields) because
        OpenRAG's tool-result parser (``parse_knowledge_chunks``) only keeps items that have one of
        ``text`` / ``filename`` / ``chunk_id`` — without them the chat UI shows "Found 0 results"
        even though the agent received the full graph. The origin item always reports BOTH
        directions (they live on the same page, so it costs nothing); ``direction`` only limits
        which neighbours are expanded."""
        origin = (self.repo_path or "").strip().strip("[]{}() \t\n\r`\"'")
        if not origin:
            msg = "No repo_path provided. Use search_wiki to find one."
            return [Data(data={"filename": "", "text": msg, "error": msg})]
        direction = (getattr(self, "direction", "both") or "both").strip().lower()
        hops = max(1, min(3, int(getattr(self, "hops", 1) or 1)))
        max_nodes = max(1, int(getattr(self, "max_nodes", 40) or 40))
        try:
            client = self._client()
            root = self._fetch_file_page(client, origin)
        except Exception as e:  # noqa: BLE001
            msg = f"OpenSearch query failed: {e}"
            return [Data(data={"filename": origin, "text": msg, "error": msg, "repo_path": origin})]
        if root is None:
            msg = f"No wiki page found for '{origin}'. Try search_wiki."
            return [Data(data={"filename": origin, "text": msg, "error": msg, "repo_path": origin})]

        want_dep = direction in ("both", "depends_on")
        want_call = direction in ("both", "called_by")

        visited = {origin}
        frontier = [origin]
        depends_edges: dict[str, list[str]] = {}
        called_edges: dict[str, list[str]] = {}
        neighbours: dict[str, dict] = {}

        for hop in range(1, hops + 1):
            next_frontier: list[str] = []
            for node in frontier:
                try:
                    page = root if node == origin else self._fetch_file_page(client, node)
                except Exception:  # noqa: BLE001 - skip this node, keep the rest of the walk
                    page = None
                if not page:
                    continue
                deps = self._parse("wiki_depends_on", page) if want_dep else []
                calls = self._parse("wiki_called_by", page) if want_call else []
                depends_edges[node] = deps
                called_edges[node] = calls
                for relation, targets in (("depends_on", deps), ("called_by", calls)):
                    for nb in targets:
                        if nb == origin:
                            continue
                        if nb not in neighbours and len(neighbours) < max_nodes:
                            neighbours[nb] = {
                                **self._node_summary(client, nb),
                                "relation": relation,
                                "via": node,
                                "hop": hop,
                            }
                        if nb not in visited:
                            visited.add(nb)
                            next_frontier.append(nb)
            frontier = next_frontier
            if not frontier or len(neighbours) >= max_nodes:
                break

        # The origin page always carries both edge lists — report both regardless of `direction`.
        root_deps = self._parse("wiki_depends_on", root)
        root_calls = self._parse("wiki_called_by", root)
        summary = root.get("wiki_summary", "")
        root_text = (
            f"{origin}\n"
            f"depends_on ({len(root_deps)}): {self._fmt_paths(root_deps)}\n"
            f"called_by ({len(root_calls)}): {self._fmt_paths(root_calls)}"
            + (f"\n\n{summary}" if summary else "")
        )
        items = [
            Data(
                data={
                    "filename": origin,
                    "text": root_text,
                    "repo_path": origin,
                    "relation": "origin",
                    "summary": summary,
                    "direction": direction,
                    "hops": hops,
                    "depends_on": root_deps,
                    "called_by": root_calls,
                    "edges": {"depends_on": depends_edges, "called_by": called_edges}
                    if hops > 1
                    else None,
                }
            )
        ]

        for nb in neighbours.values():
            spans = ", ".join(
                f"{s['symbol']}:{s['line_start']}-{s['line_end']}"
                for s in nb.get("symbols", [])
                if s.get("symbol")
            )
            # Always phrase as "importer → imports importee".
            label = (
                f"{nb['via']} → imports {nb['repo_path']}"
                if nb["relation"] == "depends_on"
                else f"{nb['repo_path']} → imports {nb['via']}"
            )
            text = (
                f"{nb['relation']} (hop {nb['hop']}): {label}"
                + (f"\n\n{nb['summary']}" if nb.get("summary") else "")
                + (f"\n\nsymbols: {spans}" if spans else "")
                + ("" if nb.get("found", True) else "\n\n(no wiki page indexed for this path)")
            )
            items.append(Data(data={"filename": nb["repo_path"], "text": text, **nb}))

        self.status = (
            f"walk_dependencies('{origin}', {direction}, {hops}h) → "
            f"{len(root_deps)} depends_on, {len(root_calls)} called_by, "
            f"{len(neighbours)} neighbour(s)"
        )
        return items

    async def to_toolkit(self):
        """Expose this component's tool-mode inputs as agent tools."""
        from lfx.base.tools.component_tool import ComponentToolkit

        return ComponentToolkit(component=self).get_tools()
