#!/usr/bin/env python3
"""Insert BomaRAG into Langflow's SIDEBAR_BUNDLES (source TS or built JS).

Langflow only shows a Bundles sidebar group when ``SIDEBAR_BUNDLES[].name``
matches the category key from ``custom_components/<folder>`` or the component
index. Register both ``BomaRAG`` and ``bomarag`` so either folder casing works.

    { display_name: "BomaRAG", name: "BomaRAG", icon: "BomaRAG" }
    { display_name: "BomaRAG", name: "bomarag", icon: "BomaRAG" }
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_BUNDLE_NAMES = ("BomaRAG", "bomarag")

_ANCHORS = (
    ("OpenAI", "openai", "OpenAI"),
    ("Docling", "docling", "Docling"),
    ("NVIDIA", "nvidia", "NVIDIA"),
)

_TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".html"}

_FRONTEND_ROOTS = (
    Path("/app/src/frontend/src/utils/styleUtils.ts"),
    Path("/app/src/backend/langflow/frontend"),
    Path("/app/src/backend/base/langflow/frontend"),
    Path("/app/langflow/frontend"),
)


def _field(key: str, value: str) -> str:
    """Match ``key: "value"`` or ``"key":"value"`` (TS source or minified JSON-like JS)."""
    return rf'["\']?{re.escape(key)}["\']?\s*:\s*["\']{re.escape(value)}["\']'


def _has_bundle_name(text: str, name: str) -> bool:
    return (
        re.search(
            rf"\{{(?=[^{{}}]*{_field('display_name', 'BomaRAG')})"
            rf"(?=[^{{}}]*{_field('name', name)})"
            rf"[^{{}}]*\}}",
            text,
        )
        is not None
    )


def _missing_bundle_names(text: str) -> list[str]:
    return [name for name in _BUNDLE_NAMES if not _has_bundle_name(text, name)]


def _anchor(display: str, name: str, icon: str) -> re.Pattern[str]:
    return re.compile(
        rf"\{{(?=[^{{}}]*{_field('display_name', display)})"
        rf"(?=[^{{}}]*{_field('name', name)})"
        rf"(?=[^{{}}]*{_field('icon', icon)})"
        rf"[^{{}}]+\}}"
        rf"(?P<comma>\s*,)?"
    )


def _object_for(name: str, *, quoted_keys: bool, compact: bool) -> str:
    if quoted_keys:
        return f'{{"display_name":"BomaRAG","name":"{name}","icon":"BomaRAG"}}'
    if compact:
        return f'{{display_name:"BomaRAG",name:"{name}",icon:"BomaRAG"}}'
    return f'{{ display_name: "BomaRAG", name: "{name}", icon: "BomaRAG" }}'


def _entries_for(sample: str, names: list[str]) -> tuple[str, str]:
    stripped = sample.lstrip()
    quoted_keys = bool(re.search(r'["\']display_name["\']\s*:', sample))
    compact = len(stripped) > 1 and stripped[1] not in " \n\t"
    objects = [_object_for(name, quoted_keys=quoted_keys, compact=compact) for name in names]
    if compact:
        return "", ",".join(objects)
    return "\n ", ",\n ".join(objects)


def patch_text(text: str) -> str | None:
    """Return patched text, or None when this blob has no SIDEBAR_BUNDLES anchor."""
    missing = _missing_bundle_names(text)
    if not missing:
        return text

    for display, name, icon in _ANCHORS:
        match = _anchor(display, name, icon).search(text)
        if match is None:
            continue
        sample = match.group(0)
        comma = match.group("comma") or ","
        separator, entries = _entries_for(sample, missing)
        if sample.endswith(","):
            replacement = f"{sample}{separator}{entries},"
        else:
            replacement = f"{sample}{comma}{separator}{entries}{comma}"
        return text[: match.start()] + replacement + text[match.end() :]
    return None


def _iter_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix in _TEXT_SUFFIXES and root not in seen:
                files.append(root)
                seen.add(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def default_roots() -> list[Path]:
    roots = list(_FRONTEND_ROOTS)
    for base in (Path("/app/.venv/lib"), Path("/usr/local/lib")):
        if not base.exists():
            continue
        roots.extend(base.glob("python*/site-packages/langflow/frontend"))
        roots.extend(base.glob("python*/dist-packages/langflow/frontend"))
    app = Path("/app")
    if app.exists():
        roots.extend(path for path in app.glob("**/frontend") if path.is_dir())
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve() if root.exists() else root
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return unique


def patch_paths(roots: list[Path]) -> int:
    patched = 0
    found_anchor = False
    for path in _iter_files(roots):
        original = path.read_text(encoding="utf-8", errors="ignore")
        updated = patch_text(original)
        if updated is None:
            continue
        found_anchor = True
        if updated == original:
            patched += 1
            continue
        path.write_text(updated, encoding="utf-8")
        patched += 1
        print(f"Patched Langflow SIDEBAR_BUNDLES in {path}")
    if not found_anchor:
        searched = ", ".join(str(root) for root in roots)
        raise SystemExit(
            f"Could not find a SIDEBAR_BUNDLES anchor to insert BomaRAG. Looked in: {searched}"
        )
    return patched


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    roots = [Path(arg) for arg in args] if args else default_roots()
    patch_paths(roots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
