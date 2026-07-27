"""FileNet P8 retrieve-and-window search component for the OpenRAG agent flow.

Exposes ONE tool to the agent (``filenet_document_search``) that performs the
full FileNet retrieval pipeline against the ``filenet-p8`` MCP server (the IBM
Content Services MCP sidecar):

    document_search (CBR, ranked metadata ONLY — no text)
        -> client-side top-K slice        (upstream max_results does NOT bind)
        -> projection from properties[]   (flattened fields carry known bugs;
                                           Owner/LDAP DN deliberately dropped)
        -> K parallel get_document_text_extract calls (whole extract each)
        -> failure classification         (Mode A: "" returned as success;
                                           Mode B: error text returned AS content)
        -> NFKC + ligature folding + boundary-tolerant term windowing
        -> bounded snippet per document   (token control, NOT a latency control)
        -> rows shaped for the OpenRAG citation pipeline
           {text, filename, id, chunk_id, score, mimetype, source_url}

Design notes (see filenet-p8-mcp-feature-assessment.md for the evidence):
- A result row without a ``text`` field is silently dropped by the citation
  pipeline, so retrieval failures are surfaced as explicit non-citable status
  rows and log lines — never as fabricated content, never silently.
- ``Rank`` is term-relative: used for within-query top-K ordering only, never
  cached, persisted, or compared across queries.
- An empty search term is refused: upstream silently degrades it to a
  metadata-only repository query, which looks like a successful search.
- When the ``filenet-p8`` MCP server is not registered (feature disabled),
  the tool returns a plain "not enabled" status row so the agent falls back
  to OpenSearch retrieval without error noise or fake citations.
"""

import asyncio
import json
import re
import unicodedata
from typing import Any

from lfx.base.mcp.util import MCPStdioClient, MCPStreamableHttpClient, update_tools
from lfx.custom.custom_component.component_with_cache import ComponentWithCache
from lfx.io import BoolInput, IntInput, MessageTextInput, Output, StrInput
from lfx.log.logger import logger
from lfx.schema.dataframe import DataFrame
from lfx.services.deps import get_storage_service, session_scope

# ---------------------------------------------------------------------------
# Constants and pure helpers (no lfx dependency — unit-tested from the backend)
# ---------------------------------------------------------------------------

DEFAULT_MCP_SERVER_NAME = "filenet-p8"
DEFAULT_DOCUMENT_CLASS = "Document"
DEFAULT_TOP_K = 5
# Token control set from the measured extract-size tail (p95 ≈ 60K chars,
# max ≈ 104K ≈ 26K tokens/doc): ~2000 chars keeps K=5 at ≈2,500 tokens.
DEFAULT_SNIPPET_CHAR_CAP = 2000
# Snap window edges to whitespace within this many chars before hard-cutting
# (extracts contain run-on token groups up to ~73 chars).
BOUNDARY_SNAP_CHARS = 80

SEARCH_TOOL_NAME = "document_search"
FETCH_TOOL_NAME = "get_document_text_extract"

# The IBM client returns this string AS DOCUMENT CONTENT on every download
# failure path (auth, network, non-200, retry exhaustion). It MUST be
# prefix-checked before anything reaches the model, or an HTTP error gets
# cited to the user as document text ("Mode B").
MODE_B_SENTINEL = "Error: Failed to download text content"

DISABLED_MESSAGE = (
    "FileNet search is not enabled in this deployment. "
    "Use the OpenSearch knowledge-base search instead."
)
EMPTY_TERM_MESSAGE = (
    "FileNet search requires a non-empty search term. Retry with the key "
    "words or phrase to look for. (An empty term is refused because the "
    "upstream tool would silently run a metadata-only query instead of a "
    "content search.)"
)

# Ligature folding: NFKC covers most of these, but be explicit so the matcher
# does not depend on Unicode-table details. U+FFFD (replacement char) losses
# are unrecoverable at extraction time — multi-token matching mitigates.
_LIGATURE_MAP = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "ft",
    "ﬆ": "st",
}
_LIGATURE_TABLE = str.maketrans(_LIGATURE_MAP)


def fold_ligatures(text: str) -> str:
    return text.translate(_LIGATURE_TABLE)


def normalize_for_match(text: str) -> str:
    """NFKC-normalize and fold ligatures so degraded extracts stay matchable."""
    return unicodedata.normalize("NFKC", fold_ligatures(text or ""))


def classify_extract(text: Any) -> tuple[str, str]:
    """Classify a get_document_text_extract return value.

    Returns ``(status, detail)`` where status is:
    - ``"ok"``     — real text; detail is the text itself.
    - ``"empty"``  — Mode A: the upstream tool returned "" (missing TXE
      annotation / downloadUrl, or an auth failure degraded to empty success).
    - ``"error"``  — Mode B: an upstream error string returned AS content;
      must never be shown or cited as document text.
    """
    if text is None:
        return ("empty", "no content returned for the document")
    if not isinstance(text, str):
        text = str(text)
    stripped = text.strip()
    if not stripped:
        return (
            "empty",
            "empty extract returned (Mode A): the document has no Persistent "
            "Text Extract annotation, no downloadUrl, or an upstream auth "
            "failure was degraded to an empty success",
        )
    if stripped.startswith(MODE_B_SENTINEL):
        # Do not propagate the raw upstream error body (information
        # disclosure); keep a short, bounded prefix for the logs/status row.
        return (
            "error",
            "upstream download failure returned as content (Mode B): "
            + stripped[:200],
        )
    return ("ok", text)


def parse_search_results(payload: Any) -> list[dict]:
    """Normalize the document_search tool output into a list of hit dicts.

    Accepts a list, a ``{"result": [...]}`` envelope, or a JSON string of
    either. Anything unparseable yields an empty list (logged by the caller).
    """
    if payload is None:
        return []
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return []
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        payload = payload.get("result", payload.get("results", []))
        if isinstance(payload, str):
            return parse_search_results(payload)
    if not isinstance(payload, list):
        return []
    return [hit for hit in payload if isinstance(hit, dict)]


def get_hit_property(document: dict, name: str) -> Any:
    """Read a property from the hit's ``properties[]`` list.

    ALWAYS prefer ``properties[]`` over the flattened document fields: the
    upstream flattener has confirmed bugs (a real ``0`` becomes ``null``;
    ``isVersioningEnabled`` compares a JSON boolean to the string "true").
    """
    properties = document.get("properties")
    if isinstance(properties, list):
        for prop in properties:
            if not isinstance(prop, dict):
                continue
            if name in (prop.get("symbolicName"), prop.get("name"), prop.get("id")):
                return prop.get("value")
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def project_hit(hit: dict) -> dict:
    """Project a raw search hit (~40 mostly-null properties + a duplicated
    flattened view, ~2.5-3K chars of JSON) down to the five fields the
    pipeline needs. ``Owner`` (a full LDAP DN) is deliberately dropped — it
    is directory-structure disclosure with no retrieval value.
    """
    document = hit.get("document") or {}
    if not isinstance(document, dict):
        document = {}
    # Flattened id/name are only a last resort (they are not among the
    # confirmed-buggy flattened fields, unlike version numbers/contentSize).
    guid = get_hit_property(document, "Id") or document.get("id") or ""
    title = (
        get_hit_property(document, "DocumentTitle")
        or get_hit_property(document, "Name")
        or document.get("name")
        or ""
    )
    mimetype = get_hit_property(document, "MimeType") or document.get("mimeType")
    return {
        "id": str(guid),
        "filename": str(title) if title else str(guid),
        "rank": _to_float(hit.get("Rank")),
        "mimetype": mimetype,
        "date_last_modified": get_hit_property(document, "DateLastModified"),
    }


def slice_top_k(hits: list[dict], top_k: int) -> list[dict]:
    """Client-side top-K by Rank descending.

    Hard requirement: the upstream ``max_results`` maps only to
    FULLTEXTROWLIMIT, which was measured NOT to bind (34 rows at limits of
    10/25/50), and the server never trims the row list. Without this slice a
    broad query on a production estate overflows the model context.
    """
    if top_k <= 0:
        top_k = DEFAULT_TOP_K
    ordered = sorted(hits, key=lambda hit: _to_float(hit.get("Rank")), reverse=True)
    return ordered[:top_k]


def _snap_start(text: str, start: int) -> int:
    """Move a window start forward to the next whitespace boundary (bounded)."""
    if start <= 0:
        return 0
    limit = min(len(text), start + BOUNDARY_SNAP_CHARS)
    for i in range(start, limit):
        if text[i].isspace():
            return i + 1
    return start  # run-on text: hard cut rather than losing the match


def _snap_end(text: str, end: int) -> int:
    """Move a window end backward to the previous whitespace boundary (bounded)."""
    if end >= len(text):
        return len(text)
    limit = max(0, end - BOUNDARY_SNAP_CHARS)
    for i in range(end - 1, limit, -1):
        if text[i].isspace():
            return i
    return end  # run-on text: hard cut


def locate_window(text: str, term: str, cap: int) -> tuple[str, bool]:
    """Cut a bounded snippet around the first located search-term token.

    Matching runs on NFKC + ligature-folded text (degraded extracts contain
    retained ligatures like ``proﬁle`` and U+FFFD losses; folding recovers
    the former, nothing recovers the latter). Window edges snap to whitespace
    within BOUNDARY_SNAP_CHARS so citations do not start or end mid-word,
    with a hard cut as the fallback for run-on token groups.

    Returns ``(snippet, term_located)``. When no token is found the snippet
    is the head of the document (still real evidence, flagged not-located).
    The cap is a TOKEN control: extract p95 is ~60K chars (~15K tokens), and
    fetch time is size-independent, so never "optimize" this away for speed.
    """
    if cap <= 0:
        cap = DEFAULT_SNIPPET_CHAR_CAP
    normalized = normalize_for_match(text)
    haystack = normalized.casefold()
    normalized_term = normalize_for_match(term or "").casefold()
    tokens = [t for t in re.split(r"\W+", normalized_term) if len(t) >= 3]
    if not tokens and normalized_term.strip():
        tokens = [normalized_term.strip()]

    position = -1
    for token in tokens:
        index = haystack.find(token)
        if index != -1 and (position == -1 or index < position):
            position = index

    if position == -1:
        snippet = normalized[:cap]
        if len(normalized) > cap:
            snippet = normalized[: _snap_end(normalized, cap)].rstrip() + "…"
        return (snippet.strip(), False)

    half = cap // 2
    start = max(0, position - half)
    end = min(len(normalized), start + cap)
    start = _snap_start(normalized, start)
    end = _snap_end(normalized, end)
    snippet = normalized[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(normalized):
        snippet = snippet + "…"
    return (snippet, True)


def build_viewer_url(template: str, guid: str) -> str:
    """Fill a viewer URL template; ``{id}`` gets the GUID without braces."""
    template = (template or "").strip()
    if not template or not guid:
        return ""
    return template.replace("{id}", str(guid).strip("{}"))


def build_source_rows(
    projected: list[dict],
    extracts: list[tuple[str, str]],
    term: str,
    snippet_char_cap: int,
    viewer_url_template: str,
) -> tuple[list[dict], list[str]]:
    """Combine projected hits and classified extracts into citation rows.

    Returns ``(rows, failures)``. Only rows for successfully retrieved and
    windowed text carry a ``text`` field (the citation contract); failures
    are returned as human-readable notes for the status row and the logs.
    """
    rows: list[dict] = []
    failures: list[str] = []
    for hit, (status, detail) in zip(projected, extracts):
        label = hit.get("filename") or hit.get("id") or "<unknown document>"
        if status != "ok":
            failures.append(f"{label}: {detail}")
            continue
        snippet, located = locate_window(detail, term, snippet_char_cap)
        if not snippet:
            failures.append(f"{label}: extract contained no usable text")
            continue
        row = {
            "text": snippet,
            "filename": hit.get("filename") or hit.get("id"),
            "id": hit.get("id"),
            "chunk_id": hit.get("id"),
            "score": hit.get("rank", 0.0),
            "mimetype": hit.get("mimetype"),
            "source_url": build_viewer_url(viewer_url_template, hit.get("id", "")),
            "term_located": located,
        }
        if hit.get("date_last_modified"):
            row["date_last_modified"] = hit["date_last_modified"]
        rows.append(row)
    return rows, failures


def _status_row(status: str, message: str) -> dict:
    """A non-citable tool-output row: NO ``text`` key, so the citation
    pipeline drops it while the agent still sees the message."""
    return {"status": status, "message": message}


# ---------------------------------------------------------------------------
# Langflow component
# ---------------------------------------------------------------------------


class FileNetSearchComponent(ComponentWithCache):
    display_name = "FileNet P8 Search"
    description = (
        "Live FileNet P8 (Content Manager) keyword search via the IBM Content "
        "Services MCP server, with retrieve-and-window text fetching for "
        "grounded, cited answers."
    )
    documentation: str = "https://docs.openr.ag/"
    icon = "search"
    name = "FileNetSearch"

    inputs = [
        MessageTextInput(
            name="search_term",
            display_name="Search Term",
            info=(
                "Keywords or a quoted phrase to search for in FileNet P8 "
                "document content (lexical CBR search). Must be non-empty."
            ),
            tool_mode=True,
        ),
        StrInput(
            name="mcp_server_name",
            display_name="MCP Server Name",
            value=DEFAULT_MCP_SERVER_NAME,
            advanced=True,
            info="Name of the registered Langflow MCP server for the FileNet sidecar.",
        ),
        StrInput(
            name="document_class",
            display_name="Document Class",
            value=DEFAULT_DOCUMENT_CLASS,
            advanced=True,
            info=(
                "FileNet document class pinned at configuration time (the "
                "list_root_classes/determine_class prerequisite chain is "
                "pre-resolved; the class must be CBR-enabled)."
            ),
        ),
        IntInput(
            name="top_k",
            display_name="Top K Documents",
            value=DEFAULT_TOP_K,
            advanced=True,
            info=(
                "Documents fetched and cited per query. Sliced CLIENT-SIDE: "
                "the upstream max_results does not bound the result set."
            ),
        ),
        IntInput(
            name="snippet_char_cap",
            display_name="Snippet Character Cap",
            value=DEFAULT_SNIPPET_CHAR_CAP,
            advanced=True,
            info=(
                "Per-document snippet cap in characters. A token-budget "
                "control (extract p95 is ~60K chars); not a latency control."
            ),
        ),
        StrInput(
            name="viewer_url_template",
            display_name="Viewer URL Template",
            value="",
            advanced=True,
            info=(
                "Optional citation link template; {id} is replaced with the "
                "FileNet GUID without braces."
            ),
        ),
        BoolInput(
            name="verify_ssl",
            display_name="Verify SSL",
            value=True,
            advanced=True,
        ),
    ]

    outputs = [
        Output(
            display_name="Search Results",
            name="search_results",
            # The method name is the agent-visible tool name when the
            # component is exposed as a tool — keep it self-describing.
            method="filenet_document_search",
        ),
    ]

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self.stdio_client: MCPStdioClient = MCPStdioClient(
            component_cache=self._shared_component_cache
        )
        self.streamable_http_client: MCPStreamableHttpClient = MCPStreamableHttpClient(
            component_cache=self._shared_component_cache
        )

    def _get_session_context(self) -> str | None:
        """Langflow session id + server name, for persistent MCP sessions."""
        graph = getattr(self, "graph", None)
        session_id = getattr(graph, "session_id", None) if graph is not None else None
        if not session_id:
            return None
        server_name = getattr(self, "mcp_server_name", "") or DEFAULT_MCP_SERVER_NAME
        return f"{session_id}_{server_name}"

    async def _resolve_server_config(self, server_name: str) -> dict | None:
        """Fetch the registered MCP server config from the Langflow DB.

        Returns None when the server is not registered (feature disabled) or
        resolution is impossible; the caller degrades gracefully.
        """
        try:
            from langflow.api.v2.mcp import get_server
            from langflow.services.database.models.user.crud import get_user_by_id

            from lfx.services.deps import get_settings_service
        except ImportError as error:
            await logger.awarning(
                f"FileNet search: Langflow MCP APIs unavailable ({error}); "
                "treating the FileNet tool as disabled."
            )
            return None

        try:
            async with session_scope() as db:
                if not self.user_id:
                    await logger.awarning(
                        "FileNet search: no user id on the component; cannot "
                        "resolve the MCP server config."
                    )
                    return None
                current_user = await get_user_by_id(db, self.user_id)
                server_config = await get_server(
                    server_name,
                    current_user,
                    db,
                    storage_service=get_storage_service(),
                    settings_service=get_settings_service(),
                )
        except Exception as error:  # noqa: BLE001 - degrade, never break the agent
            await logger.awarning(
                f"FileNet search: failed to resolve MCP server "
                f"'{server_name}' ({error}); treating the FileNet tool as disabled."
            )
            return None

        if not server_config:
            return None
        if "verify_ssl" not in server_config:
            server_config["verify_ssl"] = getattr(self, "verify_ssl", True)
        return server_config

    async def _load_tools(self, server_name: str, server_config: dict) -> dict:
        """Connect to the sidecar and return the tool cache (name -> tool)."""
        _, _tool_list, tool_cache = await update_tools(
            server_name=server_name,
            server_config=server_config,
            mcp_stdio_client=self.stdio_client,
            mcp_streamable_http_client=self.streamable_http_client,
        )
        return tool_cache or {}

    @staticmethod
    def _content_to_text(output: Any) -> str:
        """Concatenate the text content items of an MCP tool result."""
        content = getattr(output, "content", None) or []
        parts: list[str] = []
        for item in content:
            item_dict = item.model_dump() if hasattr(item, "model_dump") else item
            if isinstance(item_dict, dict) and item_dict.get("type") == "text":
                parts.append(item_dict.get("text") or "")
        return "\n".join(parts)

    async def _fetch_extract(self, fetch_tool: Any, guid: str) -> tuple[str, str]:
        """Fetch one document's text extract; classify instead of raising."""
        try:
            output = await fetch_tool.coroutine(identifier=guid)
        except Exception as error:  # noqa: BLE001 - per-document failure isolation
            await logger.awarning(
                f"FileNet search: get_document_text_extract failed for "
                f"{guid}: {error}"
            )
            return ("error", f"text-extract call failed: {error}")
        return classify_extract(self._content_to_text(output))

    async def filenet_document_search(self) -> DataFrame:
        """Run the full FileNet retrieve-and-window pipeline (never raises)."""
        term = (getattr(self, "search_term", "") or "").strip()
        if not term:
            await logger.awarning(
                "FileNet search: refused an empty search term (upstream would "
                "silently run a metadata-only query)."
            )
            return DataFrame([_status_row("error", EMPTY_TERM_MESSAGE)])

        server_name = (
            getattr(self, "mcp_server_name", "") or DEFAULT_MCP_SERVER_NAME
        ).strip()
        server_config = await self._resolve_server_config(server_name)
        if not server_config:
            return DataFrame([_status_row("disabled", DISABLED_MESSAGE)])

        try:
            await logger.ainfo(
                f"FileNet search: querying '{server_name}' "
                f"(class={getattr(self, 'document_class', DEFAULT_DOCUMENT_CLASS)})."
            )
            session_context = self._get_session_context()
            if session_context:
                self.stdio_client.set_session_context(session_context)
                self.streamable_http_client.set_session_context(session_context)

            tool_cache = await self._load_tools(server_name, server_config)
            search_tool = tool_cache.get(SEARCH_TOOL_NAME)
            fetch_tool = tool_cache.get(FETCH_TOOL_NAME)
            if search_tool is None or fetch_tool is None:
                await logger.awarning(
                    f"FileNet search: required tools missing on '{server_name}' "
                    f"(have: {sorted(tool_cache)}). Is the sidecar running the "
                    "Core server config?"
                )
                return DataFrame(
                    [
                        _status_row(
                            "error",
                            "FileNet search is misconfigured: the MCP server "
                            "does not expose document_search/"
                            "get_document_text_extract. Fall back to the "
                            "OpenSearch knowledge-base search.",
                        )
                    ]
                )

            top_k = int(getattr(self, "top_k", DEFAULT_TOP_K) or DEFAULT_TOP_K)
            document_class = (
                getattr(self, "document_class", DEFAULT_DOCUMENT_CLASS)
                or DEFAULT_DOCUMENT_CLASS
            ).strip()

            search_output = await search_tool.coroutine(
                search_parameters={
                    "search_class": document_class,
                    "search_properties": [],
                },
                search_term=term,
                max_results=top_k,
            )
            hits = parse_search_results(self._content_to_text(search_output))
            await logger.ainfo(
                f"FileNet search: document_search returned {len(hits)} hits "
                f"(top_k={top_k})."
            )
            if not hits:
                return DataFrame(
                    [
                        _status_row(
                            "no_results",
                            f"FileNet search found no documents matching "
                            f"'{term}' in this object store.",
                        )
                    ]
                )

            projected = [project_hit(hit) for hit in slice_top_k(hits, top_k)]
            projected = [hit for hit in projected if hit["id"]]
            if not projected:
                return DataFrame(
                    [
                        _status_row(
                            "error",
                            "FileNet search returned hits without document "
                            "ids; nothing could be retrieved.",
                        )
                    ]
                )

            extracts = await asyncio.gather(
                *(self._fetch_extract(fetch_tool, hit["id"]) for hit in projected)
            )
            snippet_cap = int(
                getattr(self, "snippet_char_cap", DEFAULT_SNIPPET_CHAR_CAP)
                or DEFAULT_SNIPPET_CHAR_CAP
            )
            rows, failures = build_source_rows(
                projected,
                list(extracts),
                term,
                snippet_cap,
                getattr(self, "viewer_url_template", "") or "",
            )

            for failure in failures:
                await logger.awarning(f"FileNet search: retrieval failure — {failure}")
            if failures:
                rows.append(
                    _status_row(
                        "partial_failure" if rows else "failure",
                        f"{len(failures)} of {len(projected)} FileNet "
                        f"document(s) could not be retrieved: "
                        + "; ".join(failures),
                    )
                )
            await logger.ainfo(
                f"FileNet search: returning {len(rows)} row(s) "
                f"({len(failures)} failure(s))."
            )
            return DataFrame(rows)
        except Exception as error:  # noqa: BLE001 - the tool must not blow up the agent
            await logger.aexception(f"FileNet search failed: {error}")
            return DataFrame(
                [
                    _status_row(
                        "error",
                        f"FileNet search failed: {error}. Fall back to the "
                        "OpenSearch knowledge-base search if appropriate.",
                    )
                ]
            )
