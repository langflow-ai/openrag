"""Every custom component embedded in a flow must match its source file.

Langflow runs the copy of a component stored inside the flow JSON, not the file
in ``custom_components/``. It also compares the two to decide whether a node is
stale: if they differ *as text*, it marks the component outdated and refuses to
build the flow — which breaks onboarding, with an error that says nothing about
formatting.

That is not hypothetical. In #2389 a formatter reflowed
``export_docling_document.py`` (import wrapping, a signature split across lines,
one blank line) after the flow's copy had been regenerated. The code was
functionally identical and the flow was blocked anyway.

So this compares every embedded custom component against its file, byte for
byte, across every flow.
"""

import difflib
import hashlib
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENT_DIR = REPO_ROOT / "custom_components" / "openrag"
FLOW_DIR = REPO_ROOT / "flows"

# Guards against the discovery below silently finding nothing and the whole
# suite passing vacuously. Raise this if more components get embedded.
MINIMUM_EMBEDDED_COMPONENTS = 12

CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(", re.MULTILINE)


def _component_sources() -> dict[str, tuple[Path, str]]:
    """Map each class name defined under custom_components/ to its file."""
    sources: dict[str, tuple[Path, str]] = {}
    for path in sorted(COMPONENT_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text()
        for class_name in CLASS_RE.findall(text):
            sources[class_name] = (path, text)
    return sources


def _embedded_components() -> list[tuple[str, str, Path, str, str]]:
    """Find (flow, node id, source path, embedded code, source text) for each match.

    A flow node is matched to a component file by the class it defines, so nodes
    holding Langflow's built-in components are skipped rather than compared
    against something they were never copied from.
    """
    sources = _component_sources()
    found: list[tuple[str, str, Path, str, str]] = []

    for flow_path in sorted(FLOW_DIR.glob("*.json")):
        flow = json.loads(flow_path.read_text())
        for node in flow.get("data", {}).get("nodes", []):
            data = node.get("data", {})
            code = (data.get("node", {}).get("template", {}).get("code") or {}).get("value")
            if not isinstance(code, str):
                continue
            for class_name in CLASS_RE.findall(code):
                if class_name in sources:
                    source_path, source_text = sources[class_name]
                    found.append(
                        (flow_path.name, data.get("id", "?"), source_path, code, source_text)
                    )
                    break
    return found


EMBEDDED = _embedded_components()


def _regeneration_hint(flow_name: str, node_id: str, source_path: Path) -> str:
    return (
        f"\n\nThe flow's copy has drifted from {source_path.relative_to(REPO_ROOT)}.\n"
        "Langflow will mark this component outdated and refuse to build the flow.\n"
        "Regenerate the embedded copy:\n\n"
        "    python - <<'EOF'\n"
        "    import json\n"
        f"    path = 'flows/{flow_name}'\n"
        "    flow = json.load(open(path))\n"
        f"    src = open('{source_path.relative_to(REPO_ROOT)}').read()\n"
        "    for node in flow['data']['nodes']:\n"
        f"        if node['data']['id'] == '{node_id}':\n"
        "            node['data']['node']['template']['code']['value'] = src\n"
        "    with open(path, 'w') as f:\n"
        "        json.dump(flow, f, indent=2, ensure_ascii=False)\n"
        "        f.write('\\n')\n"
        "    EOF\n"
    )


def test_discovery_found_the_embedded_components():
    """A bug in discovery would make every other test here pass for free."""
    assert len(EMBEDDED) >= MINIMUM_EMBEDDED_COMPONENTS, (
        f"Only found {len(EMBEDDED)} embedded custom components, expected at least "
        f"{MINIMUM_EMBEDDED_COMPONENTS}. Either discovery broke or components were "
        "removed from the flows — check before lowering this number."
    )


@pytest.mark.parametrize(
    ("flow_name", "node_id", "source_path", "embedded", "source"),
    EMBEDDED,
    ids=[f"{flow}:{node}" for flow, node, _, _, _ in EMBEDDED],
)
def test_embedded_component_matches_its_source(flow_name, node_id, source_path, embedded, source):
    """Byte-for-byte, because Langflow compares text and not behaviour."""
    if embedded == source:
        return

    diff = "\n".join(
        difflib.unified_diff(
            embedded.splitlines(),
            source.splitlines(),
            fromfile=f"{flow_name}:{node_id} (embedded)",
            tofile=str(source_path.relative_to(REPO_ROOT)),
            lineterm="",
            n=2,
        )
    )
    pytest.fail(
        f"{flow_name} / {node_id} does not match its source file."
        f"{_regeneration_hint(flow_name, node_id, source_path)}\n{diff}"
    )


def test_whitespace_only_drift_is_still_a_failure():
    """Proves the check would catch the #2389 regression, not just gross edits.

    Without this, a comparison that normalised whitespace would pass this suite
    while leaving flows blocked in exactly the way that broke onboarding.
    """
    flow_name, node_id, source_path, embedded, source = EMBEDDED[0]

    # The real drift was import wrapping, a split signature, and a blank line.
    reformatted = embedded.replace("\n\n\n", "\n\n", 1)
    assert reformatted != embedded, "expected a blank-line change to alter the text"

    with pytest.raises(pytest.fail.Exception):
        test_embedded_component_matches_its_source(
            flow_name, node_id, source_path, reformatted, source
        )


def test_no_two_components_share_a_class_name():
    """Discovery matches on class name, so duplicates would compare against the wrong file."""
    seen: dict[str, Path] = {}
    duplicates = []
    for path in sorted(COMPONENT_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for class_name in CLASS_RE.findall(path.read_text()):
            if class_name in seen:
                duplicates.append(f"{class_name}: {seen[class_name].name} and {path.name}")
            seen[class_name] = path

    assert not duplicates, "Class names must be unique for flow matching: " + "; ".join(duplicates)


def test_embedded_copies_are_reported_with_stable_hashes():
    """A quick inventory, so a failure elsewhere is easy to correlate by hash."""
    hashes = {
        f"{flow}:{node}": hashlib.sha256(embedded.encode()).hexdigest()[:16]
        for flow, node, _, embedded, _ in EMBEDDED
    }
    assert len(hashes) == len(EMBEDDED)
