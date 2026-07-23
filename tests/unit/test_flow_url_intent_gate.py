import json
from pathlib import Path


def _load_flow(flow_path: str) -> dict:
    return json.loads(Path(flow_path).read_text(encoding="utf-8"))


def _url_node(flow: dict) -> dict:
    return next(
        node
        for node in flow["data"]["nodes"]
        if node.get("data", {}).get("node", {}).get("display_name") == "URL"
    )


def test_url_component_gates_fetch_on_trusted_user_message():
    """VULN-13906: ensure_url() must refuse URLs absent from the trusted current-user-message
    global before the SSRF check, so a document-driven tool call can't reach the network."""
    code = Path("flows/components/url.py").read_text(encoding="utf-8")

    assert 'name="openrag_current_user_message"' in code
    assert '"openrag_current_user_message": "OPENRAG_CURRENT_USER_MESSAGE"' in code
    assert "def _openrag_trusted_user_message(self) -> str:" in code

    # The intent check must run before the SSRF check, not after.
    intent_idx = code.index("trusted_user_message = self._openrag_trusted_user_message()")
    ssrf_idx = code.index("validate_url_for_ssrf(url, warn_only=False)")
    assert intent_idx < ssrf_idx


def test_embedded_url_node_is_synced_and_has_new_input_wired():
    py_code = Path("flows/components/url.py").read_text(encoding="utf-8")
    flow = _load_flow("flows/openrag_url_mcp.json")
    node = _url_node(flow)

    embedded_code = node["data"]["node"]["template"]["code"]["value"]
    assert embedded_code == py_code, (
        "flows/openrag_url_mcp.json URL node embedded code is out of sync with "
        "flows/components/url.py — re-run scripts/update_flow_components.py"
    )

    template = node["data"]["node"]["template"]
    assert "openrag_current_user_message" in template
    field = template["openrag_current_user_message"]
    assert field["load_from_db"] is True
    assert field["value"] == "OPENRAG_CURRENT_USER_MESSAGE"

    assert "openrag_current_user_message" in node["data"]["node"]["field_order"]


def test_url_component_allowlist_check_runs_before_ssrf_and_intent_check():
    """VULN-13906: ensure_url() must run intent -> allowlist -> SSRF, in that order."""
    code = Path("flows/components/url.py").read_text(encoding="utf-8")

    assert 'os.environ.get("OPENRAG_URL_INGEST_ALLOWED_HOSTS"' in code
    assert 'ipaddress.ip_network("100.64.0.0/10")' in code
    assert "def _openrag_assert_url_ingest_allowed(url: str) -> None:" in code

    intent_idx = code.index("trusted_user_message = self._openrag_trusted_user_message()")
    allowlist_idx = code.index("_openrag_assert_url_ingest_allowed(url)")
    ssrf_idx = code.index("validate_url_for_ssrf(url, warn_only=False)")
    assert intent_idx < allowlist_idx < ssrf_idx


def test_url_component_cgnat_constant_matches_backend_ssrf_guard():
    """The embedded duplicate must stay in sync with src/utils/ssrf_guard.py."""
    backend_code = Path("src/utils/ssrf_guard.py").read_text(encoding="utf-8")
    flow_code = Path("flows/components/url.py").read_text(encoding="utf-8")

    assert 'ipaddress.ip_network("100.64.0.0/10")' in backend_code
    assert 'ipaddress.ip_network("100.64.0.0/10")' in flow_code
