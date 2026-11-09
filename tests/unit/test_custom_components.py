"""Structural checks that apply to every custom Langflow component.

These are deliberately generic: they run over whatever lives in
``custom_components/openrag/`` rather than naming individual components, so a
new component is covered the moment it is added.

Two of them exist because of a specific failure mode. ``autofix.ci``
(`.github/workflows/autofix.ci.yml`) runs ``ruff check --fix`` and
``ruff format`` on changed files and **pushes the result directly**. A component
that is not already clean therefore gets rewritten by CI *after* review — and
since the flow JSON carries its own copy of the component source, which ruff has
no reason to touch, the two silently diverge. Langflow then compares them as
text, marks the node outdated, and refuses to build the flow. That is what broke
onboarding after #2389.

Keeping every component ruff-clean means CI has nothing left to rewrite, so the
drift cannot be introduced that way in the first place.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENT_DIR = REPO_ROOT / "custom_components" / "openrag"
FLOW_DIR = REPO_ROOT / "flows"

COMPONENT_FILES = sorted(p for p in COMPONENT_DIR.glob("*.py") if p.name != "__init__.py")
COMPONENT_IDS = [p.name for p in COMPONENT_FILES]

# Matches the flags autofix.ci uses, so this test agrees with what CI would do.
RUFF_CHECK_ARGS = ["check", "--extend-ignore", "F401"]


def _ruff(*args: str) -> subprocess.CompletedProcess:
    ruff = REPO_ROOT / ".venv" / "bin" / "ruff"
    if not ruff.exists():
        pytest.skip("ruff is not installed in this environment")
    return subprocess.run(
        [str(ruff), *args], capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )


def _class_defs(tree: ast.Module) -> list[ast.ClassDef]:
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def _keyword_value(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if (
            kw.arg == name
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _calls_in_class_attr(cls: ast.ClassDef, attr: str) -> list[ast.Call]:
    """Every call in a class-level list assignment, e.g. ``inputs = [...]``."""
    calls: list[ast.Call] = []
    for node in cls.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = node.targets
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == attr for t in targets):
            continue
        if isinstance(value, (ast.List, ast.Tuple)):
            calls += [e for e in value.elts if isinstance(e, ast.Call)]
    return calls


def test_there_are_components_to_check():
    """Guards against the glob silently matching nothing."""
    assert COMPONENT_FILES, f"No component files found under {COMPONENT_DIR}"


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_source_is_valid_python(path: Path):
    """A syntax error here ships a component that cannot load at all."""
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        pytest.fail(f"{path.name} is not valid Python: line {exc.lineno}: {exc.msg}")


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_is_ruff_format_clean(path: Path):
    """If CI would reformat it, CI will desync the flow's embedded copy."""
    result = _ruff("format", "--check", str(path.relative_to(REPO_ROOT)))
    if result.returncode != 0:
        diff = _ruff("format", "--diff", str(path.relative_to(REPO_ROOT))).stdout
        pytest.fail(
            f"{path.name} is not ruff-format clean.\n\n"
            "autofix.ci runs `ruff format` on changed files and pushes the result, "
            "which would rewrite this file after review and leave the copy embedded "
            "in flows/*.json stale — blocking the flow build.\n\n"
            f"Fix with:  ruff format {path.relative_to(REPO_ROOT)}\n"
            "then regenerate the flow copies (see test_flow_component_sync.py).\n\n"
            f"{diff}"
        )


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_is_ruff_check_clean(path: Path):
    """Same hazard as formatting: `ruff check --fix` also rewrites and pushes."""
    result = _ruff(*RUFF_CHECK_ARGS, str(path.relative_to(REPO_ROOT)))
    if result.returncode != 0:
        pytest.fail(
            f"{path.name} has ruff lint findings that autofix.ci would fix and push, "
            "desyncing the copy embedded in flows/*.json.\n\n"
            f"Fix with:  ruff check --fix --extend-ignore F401 {path.relative_to(REPO_ROOT)}\n"
            "then regenerate the flow copies (see test_flow_component_sync.py).\n\n"
            f"{result.stdout}"
        )


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_outputs_reference_real_methods(path: Path):
    """An Output naming a method that does not exist fails only at runtime."""
    tree = ast.parse(path.read_text())
    for cls in _class_defs(tree):
        methods = {
            n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for call in _calls_in_class_attr(cls, "outputs"):
            method = _keyword_value(call, "method")
            if method is None:
                continue
            assert method in methods, (
                f"{path.name}: {cls.name} declares an output calling `{method}()`, "
                f"but that method is not defined on the class. Defined: {sorted(methods)}"
            )


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_input_names_are_unique(path: Path):
    """Duplicate input names silently shadow each other in the template."""
    tree = ast.parse(path.read_text())
    for cls in _class_defs(tree):
        names = [
            name
            for call in _calls_in_class_attr(cls, "inputs")
            if (name := _keyword_value(call, "name")) is not None
        ]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, (
            f"{path.name}: {cls.name} declares duplicate input names: {duplicates}"
        )


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=COMPONENT_IDS)
def test_component_output_names_are_unique(path: Path):
    """Duplicate output names make the wrong handle resolve downstream."""
    tree = ast.parse(path.read_text())
    for cls in _class_defs(tree):
        names = [
            name
            for call in _calls_in_class_attr(cls, "outputs")
            if (name := _keyword_value(call, "name")) is not None
        ]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert not duplicates, (
            f"{path.name}: {cls.name} declares duplicate output names: {duplicates}"
        )


def _embedded_code_blocks() -> list[tuple[str, str, str]]:
    """(flow name, node id, code) for every node in every flow that carries source."""
    blocks = []
    for flow_path in sorted(FLOW_DIR.glob("*.json")):
        flow = json.loads(flow_path.read_text())
        for node in flow.get("data", {}).get("nodes", []):
            data = node.get("data", {})
            code = (data.get("node", {}).get("template", {}).get("code") or {}).get("value")
            if isinstance(code, str) and code.strip():
                blocks.append((flow_path.name, data.get("id", "?"), code))
    return blocks


EMBEDDED_CODE = _embedded_code_blocks()


def test_flows_carry_embedded_code():
    """Guards against the discovery above returning nothing."""
    assert EMBEDDED_CODE, "No embedded component code found in flows/*.json"


@pytest.mark.parametrize(
    ("flow_name", "node_id", "code"),
    EMBEDDED_CODE,
    ids=[f"{flow}:{node}" for flow, node, _ in EMBEDDED_CODE],
)
def test_embedded_code_is_valid_python(flow_name: str, node_id: str, code: str):
    """Truncated or corrupted embedded source breaks the flow at build time."""
    try:
        ast.parse(code)
    except SyntaxError as exc:
        pytest.fail(
            f"{flow_name} / {node_id} has embedded code that is not valid Python: "
            f"line {exc.lineno}: {exc.msg}"
        )


@pytest.mark.parametrize(
    ("flow_name", "node_id", "code"),
    EMBEDDED_CODE,
    ids=[f"{flow}:{node}" for flow, node, _ in EMBEDDED_CODE],
)
def test_embedded_code_defines_a_class(flow_name: str, node_id: str, code: str):
    """Every Langflow node's code should define its component class."""
    tree = ast.parse(code)
    assert _class_defs(tree), (
        f"{flow_name} / {node_id} embeds code that defines no class; "
        "Langflow will not be able to resolve the component."
    )


def test_python_version_matches_the_interpreter_running_these_checks():
    """ast parsing is version-sensitive; record what validated the sources."""
    assert sys.version_info >= (3, 11), (
        "These components use `X | None` syntax in annotations; parse under 3.11+."
    )
