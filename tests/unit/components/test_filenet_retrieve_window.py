"""Unit tests for the FileNet retrieve-and-window component's pure logic.

The component file lives in flows/components/ (embedded into the agent flow
JSON) and imports the Langflow component SDK (lfx), which is not installed in
the backend environment. The pure retrieval-correctness logic is deliberately
module-level and lfx-free, so these tests load the file with lfx/langflow
stubbed out in sys.modules.

Correctness requirements under test (traceable to
filenet-p8-mcp-feature-assessment.md):
- Mode B sentinel: upstream download errors returned AS content must be
  rejected, never cited.
- Mode A: an empty extract is a loud retrieval failure, never a silent drop.
- Top-K slicing is client-side (upstream max_results does not bind).
- Projection reads properties[], never the buggy flattened fields; Owner
  (LDAP DN) is dropped.
- NFKC + ligature folding + boundary-tolerant windowing on degraded extracts.
- Per-document character cap.
- Empty search term is refused.
- Emitted rows carry the citation contract fields (non-empty text, filename,
  id, chunk_id, score); failures become non-citable status rows.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_COMPONENT_PATH = (
    Path(__file__).resolve().parents[3] / "flows" / "components" / "filenet_retrieve_window.py"
)


def _stub_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_lfx_stubs() -> None:
    class _Input:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Output:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _ComponentWithCache:
        _shared_component_cache = None

        def __init__(self, **data):
            self.__dict__.update(data)

    class _MCPClient:
        def __init__(self, component_cache=None):
            self.component_cache = component_cache

        def set_session_context(self, context):
            self.session_context = context

    async def _update_tools(**kwargs):  # pragma: no cover - not exercised here
        return None, [], {}

    class _AsyncLogger:
        async def ainfo(self, *a, **k):
            pass

        async def awarning(self, *a, **k):
            pass

        async def aexception(self, *a, **k):
            pass

    class _DataFrame(list):
        def __init__(self, data=None, **kwargs):
            super().__init__(data or [])

    _stub_module("lfx")
    _stub_module("lfx.base")
    _stub_module("lfx.base.mcp")
    _stub_module(
        "lfx.base.mcp.util",
        MCPStdioClient=_MCPClient,
        MCPStreamableHttpClient=_MCPClient,
        update_tools=_update_tools,
    )
    _stub_module("lfx.custom")
    _stub_module("lfx.custom.custom_component")
    _stub_module(
        "lfx.custom.custom_component.component_with_cache",
        ComponentWithCache=_ComponentWithCache,
    )
    _stub_module(
        "lfx.io",
        BoolInput=_Input,
        IntInput=_Input,
        MessageTextInput=_Input,
        Output=_Output,
        StrInput=_Input,
    )
    _stub_module("lfx.log")
    _stub_module("lfx.log.logger", logger=_AsyncLogger())
    _stub_module("lfx.schema")
    _stub_module("lfx.schema.dataframe", DataFrame=_DataFrame)
    _stub_module(
        "lfx.services.deps",
        get_storage_service=lambda: None,
        session_scope=None,
    )
    _stub_module("lfx.services")


_install_lfx_stubs()
_spec = importlib.util.spec_from_file_location(
    "filenet_retrieve_window_under_test", _COMPONENT_PATH
)
component = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(component)


# ---------------------------------------------------------------------------
# classify_extract: Mode A / Mode B
# ---------------------------------------------------------------------------


def test_classify_extract_ok():
    status, detail = component.classify_extract("Real document text.")
    assert status == "ok"
    assert detail == "Real document text."


@pytest.mark.parametrize("value", ["", "   ", "\n\t", None])
def test_classify_extract_mode_a_empty(value):
    status, detail = component.classify_extract(value)
    assert status == "empty"
    assert "Mode A" in detail or "no content" in detail


def test_classify_extract_mode_b_sentinel():
    poisoned = (
        "Error: Failed to download text content: Request failed with status "
        "code: 403. Response: <html>Forbidden ... internal stack trace ...</html>"
    )
    status, detail = component.classify_extract(poisoned)
    assert status == "error"
    assert "Mode B" in detail
    # The raw upstream body must be truncated (information disclosure).
    assert len(detail) < len(poisoned) + 100


def test_classify_extract_mode_b_with_leading_whitespace():
    status, _ = component.classify_extract("  Error: Failed to download text content: x")
    assert status == "error"


def test_classify_extract_sentinel_mid_text_is_content():
    """The sentinel is a PREFIX check; a document quoting the string is fine."""
    text = "The tool may print 'Error: Failed to download text content' on failure."
    status, _ = component.classify_extract(text)
    assert status == "ok"


# ---------------------------------------------------------------------------
# parse_search_results / top-K / projection
# ---------------------------------------------------------------------------


def _hit(rank, guid, title="Doc.pdf", extra_props=None, flattened=None):
    properties = [
        {"symbolicName": "Id", "value": guid},
        {"symbolicName": "DocumentTitle", "value": title},
        {"symbolicName": "MimeType", "value": "application/pdf"},
        {"symbolicName": "DateLastModified", "value": "2026-07-01T00:00:00Z"},
        {"symbolicName": "Owner", "value": "cn=admin,ou=x,dc=example,dc=com"},
        {"symbolicName": "MinorVersionNumber", "value": 0},
    ]
    if extra_props:
        properties.extend(extra_props)
    document = {"properties": properties}
    if flattened:
        document.update(flattened)
    return {"Rank": rank, "document": document}


def test_parse_search_results_accepts_json_string():
    payload = '[{"Rank": 5, "document": {}}]'
    assert component.parse_search_results(payload) == [{"Rank": 5, "document": {}}]


def test_parse_search_results_accepts_result_envelope():
    assert component.parse_search_results({"result": [{"Rank": 1}]}) == [{"Rank": 1}]


@pytest.mark.parametrize("payload", [None, "", "not json", 42, {"result": "garbage"}])
def test_parse_search_results_garbage_yields_empty(payload):
    assert component.parse_search_results(payload) == []


def test_slice_top_k_bounds_unbounded_result_sets():
    """34 rows at max_results=10 was measured upstream; we slice client-side."""
    hits = [_hit(rank=i, guid=f"{{GUID-{i}}}") for i in range(34)]
    top = component.slice_top_k(hits, 5)
    assert len(top) == 5
    assert [h["Rank"] for h in top] == [33, 32, 31, 30, 29]


def test_slice_top_k_sorts_by_rank_descending():
    hits = [_hit(74, "{A}"), _hit(358, "{B}"), _hit(200, "{C}")]
    top = component.slice_top_k(hits, 2)
    assert [h["Rank"] for h in top] == [358, 200]


def test_slice_top_k_invalid_k_falls_back_to_default():
    hits = [_hit(i, f"{{G{i}}}") for i in range(10)]
    assert len(component.slice_top_k(hits, 0)) == component.DEFAULT_TOP_K


def test_project_hit_reads_properties_not_flattened_fields():
    """The flattened view carries confirmed bugs; properties[] is the truth."""
    hit = _hit(
        358,
        "{9F6BC680-0000-C150-9223-7087CD8EDEC9}",
        title="2151932.pdf",
        flattened={
            "id": "{WRONG-FLATTENED-ID}",
            "name": "wrong-flattened-name.pdf",
            "mimeType": "application/wrong",
        },
    )
    projected = component.project_hit(hit)
    assert projected["id"] == "{9F6BC680-0000-C150-9223-7087CD8EDEC9}"
    assert projected["filename"] == "2151932.pdf"
    assert projected["mimetype"] == "application/pdf"
    assert projected["rank"] == 358.0


def test_project_hit_drops_owner_ldap_dn():
    projected = component.project_hit(_hit(1, "{G}"))
    assert "owner" not in {k.lower() for k in projected}
    assert "cn=admin" not in str(projected)


def test_project_hit_falls_back_to_flattened_id_when_no_properties():
    hit = {"Rank": 3, "document": {"id": "{FALLBACK}", "name": "n.pdf"}}
    projected = component.project_hit(hit)
    assert projected["id"] == "{FALLBACK}"
    assert projected["filename"] == "n.pdf"


def test_project_hit_handles_malformed_document():
    assert component.project_hit({"Rank": "NaNsense", "document": None})["id"] == ""
    assert component.project_hit({})["rank"] == 0.0


def test_get_hit_property_zero_value_survives():
    """The upstream falsy-zero bug (0 -> null) must not be reproduced here."""
    document = {"properties": [{"symbolicName": "MinorVersionNumber", "value": 0}]}
    assert component.get_hit_property(document, "MinorVersionNumber") == 0


# ---------------------------------------------------------------------------
# Normalization + windowing on degraded extracts
# ---------------------------------------------------------------------------


def test_normalize_folds_retained_ligatures():
    assert component.normalize_for_match("Proﬁle signiﬁcant inﬂuenced") == (
        "Profile significant influenced"
    )


def test_locate_window_finds_ligature_corrupted_term():
    """A user searching 'profile' must match the extract's 'Proﬁle'."""
    text = "Colorado Demographic Proﬁle for the planning region."
    snippet, located = component.locate_window(text, "profile", 200)
    assert located is True
    assert "Profile" in snippet


def test_locate_window_u_fffd_loss_recovers_via_other_tokens():
    """'O�ce' is unrecoverable, but multi-token terms still locate."""
    text = "The State Demography O�ce publishes county population estimates."
    snippet, located = component.locate_window(text, "office population", 200)
    assert located is True
    assert "population" in snippet


def test_locate_window_caps_snippet_length():
    text = "filler " * 2000 + "NEEDLE" + " trailer" * 2000
    snippet, located = component.locate_window(text, "needle", 300)
    assert located is True
    assert "NEEDLE" in snippet
    # cap + ellipses + boundary snap tolerance
    assert len(snippet) <= 300 + 2 + component.BOUNDARY_SNAP_CHARS


def test_locate_window_snaps_to_word_boundaries():
    words = (
        " ".join(f"word{i}" for i in range(200))
        + " NEEDLE "
        + " ".join(f"tail{i}" for i in range(200))
    )
    snippet, _ = component.locate_window(words, "needle", 200)
    core = snippet.strip("…").strip()
    assert not core.startswith(("ord", "ail"))  # no mid-word cut at the edges
    assert core.split()[0].startswith(("word", "NEEDLE", "tail"))


def test_locate_window_hard_cuts_run_on_text():
    """73-char run-on groups were measured; the window must still bound."""
    run_on = "x" * 5000 + "needle" + "y" * 5000
    snippet, located = component.locate_window(run_on, "needle", 400)
    assert located is True
    assert len(snippet) <= 400 + 2  # ellipses only; no boundary to snap to


def test_locate_window_term_absent_returns_bounded_head():
    text = "alpha beta gamma " * 500
    snippet, located = component.locate_window(text, "zeta", 250)
    assert located is False
    assert 0 < len(snippet) <= 250 + 2


def test_locate_window_short_tokens_do_not_match_everything():
    snippet, located = component.locate_window("a bb ccc dddd", "of at", 100)
    # All tokens < 3 chars are dropped; the raw term itself is used.
    assert located is False


# ---------------------------------------------------------------------------
# build_source_rows: the citation contract
# ---------------------------------------------------------------------------


def _projected(guid="{G1}", title="Doc.pdf", rank=8.4):
    return {
        "id": guid,
        "filename": title,
        "rank": rank,
        "mimetype": "application/pdf",
        "date_last_modified": "2026-07-01T00:00:00Z",
    }


def test_build_source_rows_happy_path_citation_shape():
    rows, failures = component.build_source_rows(
        [_projected()],
        [("ok", "The contract shall auto-renew for successive 12-month terms.")],
        "auto-renew",
        2000,
        "https://cpd.example/nav/{id}",
    )
    assert failures == []
    assert len(rows) == 1
    row = rows[0]
    assert row["text"]  # non-empty text => citable
    assert "auto-renew" in row["text"]
    assert row["filename"] == "Doc.pdf"
    assert row["id"] == "{G1}"
    assert row["chunk_id"] == "{G1}"
    assert row["score"] == 8.4
    assert row["source_url"] == "https://cpd.example/nav/G1"


def test_build_source_rows_mode_a_failure_is_loud_not_silent():
    rows, failures = component.build_source_rows(
        [_projected()],
        [component.classify_extract("")],
        "term",
        2000,
        "",
    )
    assert rows == []
    assert len(failures) == 1
    assert "Mode A" in failures[0]


def test_build_source_rows_mode_b_never_cited():
    poisoned = "Error: Failed to download text content: HTTP 403"
    rows, failures = component.build_source_rows(
        [_projected()],
        [component.classify_extract(poisoned)],
        "term",
        2000,
        "",
    )
    assert rows == []  # the error string must never appear as citable text
    assert len(failures) == 1
    assert "Mode B" in failures[0]


def test_build_source_rows_mixed_success_and_failure():
    rows, failures = component.build_source_rows(
        [_projected("{G1}", "ok.pdf"), _projected("{G2}", "bad.pdf")],
        [("ok", "some real text about terms"), ("empty", "empty extract (Mode A)")],
        "terms",
        2000,
        "",
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "{G1}"
    assert len(failures) == 1
    assert "bad.pdf" in failures[0]


def test_status_row_is_not_citable():
    row = component._status_row("disabled", component.DISABLED_MESSAGE)
    assert "text" not in row  # citation pipeline gates on the text key
    assert row["message"] == component.DISABLED_MESSAGE


def test_build_viewer_url():
    assert component.build_viewer_url("https://x/{id}", "{ABC-123}") == "https://x/ABC-123"
    assert component.build_viewer_url("", "{ABC}") == ""
    assert component.build_viewer_url("https://x/{id}", "") == ""


# ---------------------------------------------------------------------------
# Component-level constants the flow/prompt rely on
# ---------------------------------------------------------------------------


def test_defaults_match_assessment_recommendations():
    assert component.DEFAULT_TOP_K == 5
    assert component.DEFAULT_SNIPPET_CHAR_CAP == 2000
    assert component.DEFAULT_MCP_SERVER_NAME == "filenet-p8"
    assert component.MODE_B_SENTINEL == "Error: Failed to download text content"


def test_component_tool_input_is_search_term():
    names = [getattr(i, "name", None) for i in component.FileNetSearchComponent.inputs]
    assert "search_term" in names
    tool_inputs = [
        i for i in component.FileNetSearchComponent.inputs if getattr(i, "tool_mode", False)
    ]
    assert [i.name for i in tool_inputs] == ["search_term"]
