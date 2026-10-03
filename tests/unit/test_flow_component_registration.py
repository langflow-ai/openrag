"""Every OpenRAG node in a shipped flow must resolve to a bundled component.

With ``LANGFLOW_ALLOW_CUSTOM_COMPONENTS=false``, Langflow only builds a node whose
``data.type`` it can find in its component registry. A type it cannot find is
reported as "Flow build blocked: custom components are not allowed" (#2363) —
even when the node is OpenRAG's own component, and whatever its code says.

OpenRAG's components reach that registry one way: the image copies
``custom_components/`` to ``LANGFLOW_COMPONENTS_PATH``, and Langflow loads each
subfolder as an inline bundle keyed ``ext:<bundle>:<ClassName>@extra``. It then
accepts a node type that equals that key, the bare class name, the class name
without its ``Component`` suffix, or the component's ``name`` attribute
(``lfx.utils.component_aliases``). This test applies the same rules, so renaming
a class, a ``name`` or the bundle folder without updating the flows fails here
rather than at chat or ingest time.

Code drift is a separate failure mode, covered by test_flow_component_sync.py.
"""

import ast
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_PATH = REPO_ROOT / "custom_components"
FLOW_DIR = REPO_ROOT / "flows"
EXT_KEY_RE = re.compile(r"^ext:(?P<bundle>[^:]+):(?P<class_name>[^@]+)@(?P<slot>.+)$")
CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(", re.MULTILINE)

# Guards against discovery silently finding nothing. Raise it if more OpenRAG
# nodes are added to the flows.
MINIMUM_OPENRAG_NODES = 12


def _class_attr(node: ast.ClassDef, attr: str) -> str | None:
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        else:
            continue
        if (
            any(isinstance(t, ast.Name) and t.id == attr for t in targets)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            return stmt.value.value
    return None


def _is_component_class(node: ast.ClassDef) -> bool:
    """Langflow registers classes that inherit from a component base, e.g.
    ``Component``, ``LCModelComponent`` or ``LCEmbeddingsModel``. Helper classes in
    the same files (an ``Embeddings`` client, a dataclass) are not components."""
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if "Component" in name or name.startswith("LC"):
            return True
    return False


def _bundled_components() -> dict[str, frozenset[str]]:
    """Map each bundled component class to the node types Langflow accepts for it."""
    components: dict[str, frozenset[str]] = {}
    for bundle_dir in sorted(p for p in COMPONENTS_PATH.iterdir() if p.is_dir()):
        for path in sorted(bundle_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or not _is_component_class(node):
                    continue
                aliases = {
                    f"ext:{bundle_dir.name}:{node.name}@extra",
                    node.name,
                    node.name.removesuffix("Component"),
                }
                if name := _class_attr(node, "name"):
                    aliases.add(name)
                components[node.name] = frozenset(aliases)
    return components


BUNDLED = _bundled_components()


def _openrag_nodes() -> list[tuple[str, str, str, str | None]]:
    """Find (flow, node id, node type, bundled class) for every OpenRAG node.

    A node is OpenRAG's if its type names the OpenRAG bundle or its embedded code
    defines a bundled component class. The class is None when a node claims the
    bundle but its class is not in it.
    """
    found = []
    for flow_path in sorted(FLOW_DIR.glob("*.json")):
        flow = json.loads(flow_path.read_text(encoding="utf-8"))
        for node in flow.get("data", {}).get("nodes", []):
            data = node.get("data", {})
            node_type = data.get("type") or ""
            code = (data.get("node", {}).get("template", {}).get("code") or {}).get("value")
            defined = CLASS_RE.findall(code) if isinstance(code, str) else []
            bundled = next((c for c in defined if c in BUNDLED), None)
            ext = EXT_KEY_RE.match(node_type)
            claims_bundle = ext is not None and (COMPONENTS_PATH / ext["bundle"]).is_dir()
            if bundled or claims_bundle:
                found.append((flow_path.name, data.get("id", "?"), node_type, bundled))
    return found


OPENRAG_NODES = _openrag_nodes()


def unresolved_reason(node_type: str, bundled_class: str | None) -> str | None:
    """Why Langflow would not match this node type to its bundled component, if it wouldn't."""
    if bundled_class is None:
        return f"{node_type!r} names the OpenRAG bundle, but no bundled class matches it"
    if node_type not in BUNDLED[bundled_class]:
        accepted = ", ".join(sorted(BUNDLED[bundled_class]))
        return f"{node_type!r} is not a registry alias of {bundled_class} (accepted: {accepted})"
    return None


def test_discovery_found_the_openrag_nodes():
    """A bug in discovery would make the parametrized test below pass for free."""
    assert len(OPENRAG_NODES) >= MINIMUM_OPENRAG_NODES, (
        f"Only found {len(OPENRAG_NODES)} OpenRAG nodes in the shipped flows, expected at "
        f"least {MINIMUM_OPENRAG_NODES}."
    )
    # One class per bundle file; a miss here means a component would go unchecked.
    bundle_files = [
        p
        for d in COMPONENTS_PATH.iterdir()
        if d.is_dir()
        for p in d.glob("*.py")
        if p.name != "__init__.py"
    ]
    assert len(BUNDLED) == len(bundle_files), sorted(BUNDLED)


@pytest.mark.parametrize(
    ("flow_name", "node_id", "node_type", "bundled_class"),
    OPENRAG_NODES,
    ids=[f"{flow}:{node}" for flow, node, _, _ in OPENRAG_NODES],
)
def test_openrag_node_type_resolves_to_a_bundled_component(
    flow_name, node_id, node_type, bundled_class
):
    reason = unresolved_reason(node_type, bundled_class)
    assert reason is None, (
        f"{flow_name} / {node_id}: {reason}. Langflow would block this flow with "
        "'custom components are not allowed'."
    )


@pytest.mark.parametrize(
    ("node_type", "bundled_class"),
    [
        # Type no longer matches after the component's ``name`` was renamed.
        ("OpenAICompatibleEmbeddingV2", "OpenAICompatibleEmbeddingComponent"),
        # A bundle key whose class was removed or renamed.
        ("ext:openrag:OpenAICompatibleRerankerComponent@extra", None),
        # Right class, wrong bundle folder.
        ("ext:openrag_old:OpenAICompatibleLLMComponent@extra", "OpenAICompatibleLLMComponent"),
    ],
)
def test_unresolvable_node_types_are_caught(node_type, bundled_class):
    """Proves the check fails on the drift that produced #2363's error."""
    assert unresolved_reason(node_type, bundled_class) is not None
