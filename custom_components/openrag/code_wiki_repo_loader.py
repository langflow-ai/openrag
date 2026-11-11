"""Langflow custom component: RepoLoader (git repo / archive / local path → files + manifest, NO LLM).

The ROOT of the code-wiki ingestion flow. Instead of the per-file Docling upload path, this obtains a
repo ONCE and hands the WHOLE repo to the builder in a single run, so the wiki can be globally
coherent (module pages, resolved cross-file edges).

What it does (all deterministic — regex, no model):
1. Obtain the repo, first source found wins: ``local_path`` (a directory, or a .zip / .tar.gz file
   that is unpacked), else the repo URL from an uploaded pointer file or the ``repo_url`` field:
   a git URL (``git clone --depth 1``; an HTTPS tarball download when git is missing) or a direct
   .zip / .tar.gz URL. Archives are detected by content and unpacked safely (no path traversal, no
   symlinks, size and file-count caps).
2. Walk it, honouring ignore rules (.git, __pycache__, *.pyc, venvs, node_modules, binaries, >512 KB)
   and an optional ``subtree`` scope (comma-separated repo-relative prefixes) for large repos.
3. Extract symbols with EXACT line spans (Python by indentation, C-family by brace depth) and the
   import graph, resolve edges to real ``repo_path``s, and build the repo manifest.

Emits ONE ``Data`` whose ``data["repo"]`` = ``{files, manifest, edges, repo_url, repo_ref}``; the
CodeWikiBuilder consumes it.

Wire it: ``RepoLoader → CodeWikiBuilder.repo_data``.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import posixpath
import re
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from lfx.custom.custom_component.component import Component
from lfx.io import HandleInput, IntInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data

# ---------------------------------------------------------------------------
# Ignore / language rules
# ---------------------------------------------------------------------------
IGNORE_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".ruff_cache",
    "site-packages",
    ".next",
    ".cache",
    "coverage",
    "vendor",
    "target",
    ".gradle",
}
IGNORE_DIR_SUFFIXES = (".egg-info",)
BINARY_OR_ASSET_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".jar",
    ".war",
    ".so",
    ".dylib",
    ".dll",
    ".class",
    ".pyc",
    ".pyo",
    ".pyd",
    ".o",
    ".a",
    ".bin",
    ".exe",
    ".wasm",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".wav",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".lock",
    ".map",
    ".min.js",
    ".min.css",
}
MAX_FILE_BYTES = 512 * 1024
LANG_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".m": "objc",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
}
DOC_EXTS = {".md", ".markdown", ".rst"}
BRACE_LANGS = {
    "javascript",
    "typescript",
    "java",
    "kotlin",
    "scala",
    "go",
    "rust",
    "php",
    "c",
    "cpp",
    "csharp",
    "swift",
}


def guess_language(repo_path: str) -> str:
    """Language name for a path's extension, or ``''``."""
    return LANG_BY_EXT.get(posixpath.splitext(repo_path)[1].lower(), "")


def is_ignored_dir(name: str) -> bool:
    """True for directory names that are never indexed (VCS, build output, dependencies)."""
    return name in IGNORE_DIR_NAMES or any(name.endswith(s) for s in IGNORE_DIR_SUFFIXES)


def is_ignored_file(repo_path: str) -> bool:
    """True for binary or asset files and extensions with no known language."""
    low = repo_path.lower()
    if any(low.endswith(ext) for ext in BINARY_OR_ASSET_EXTS):
        return True
    return posixpath.splitext(low)[1] not in LANG_BY_EXT


def module_of(repo_path: str) -> str:
    """Directory of a repo path; the module a file belongs to."""
    return posixpath.dirname(repo_path)


def _read_text(path: Path) -> str | None:
    """Read a regular file as text (utf-8, then latin-1). ``None`` if it is too big, not a
    regular file, or unreadable."""
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES:
            return None
    except OSError:
        return None
    for enc in ("utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return None


def _under_subtrees(repo_path: str, subtrees: list[str]) -> bool:
    """True if the path is inside one of ``subtrees`` (or no subtrees are set)."""
    if not subtrees:
        return True
    for st in subtrees:
        st = st.strip().strip("/")
        if st and (repo_path == st or repo_path.startswith(st + "/")):
            return True
    return False


def _inside(path: Path, root_real: Path) -> bool:
    """True if ``path`` is under ``root_real``."""
    try:
        path.relative_to(root_real)
    except ValueError:
        return False
    return True


def walk_files(root, subtrees=None, max_files: int = 0) -> list[dict[str, Any]]:
    """Collect the repo's ingestible files as ``{repo_path, language, text, is_doc}``.

    Symlinks are never followed. A cloned repository (or a ``local_path`` directory) can contain
    links such as ``config.py -> /proc/self/environ``; reading through them would index server
    files and secrets into the wiki. Every file is also checked to resolve inside ``root``, and is
    read through that resolved path."""
    root = Path(root)
    root_real = root.resolve()
    subtrees = subtrees or []
    out: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        rel_parts = p.relative_to(root).parts
        if any(is_ignored_dir(part) for part in rel_parts[:-1]):
            continue
        # A symlinked file, or any file under a symlinked directory, is skipped.
        if any((root.joinpath(*rel_parts[: i + 1])).is_symlink() for i in range(len(rel_parts))):
            continue
        if not p.is_file():
            continue
        real = p.resolve()
        if not _inside(real, root_real):
            continue
        rel = p.relative_to(root).as_posix()
        if is_ignored_dir(p.parent.name) or is_ignored_file(rel):
            continue
        if not _under_subtrees(rel, subtrees):
            continue
        text = _read_text(real)
        if text is None or not text.strip():
            continue
        out.append(
            {
                "repo_path": rel,
                "language": guess_language(rel),
                "text": text,
                "is_doc": posixpath.splitext(rel)[1].lower() in DOC_EXTS,
            }
        )
        if max_files and len(out) >= max_files:
            break
    return out


# ---------------------------------------------------------------------------
# Symbol extraction with exact line spans
# ---------------------------------------------------------------------------
_PY_DECL_RE = re.compile(
    r"^(?P<ind>[ \t]*)(?:async[ \t]+)?(?P<kind>def|class)[ \t]+(?P<name>[A-Za-z_]\w*)"
)


def _indent_width(s: str) -> int:
    """Width of a line's leading whitespace, with tabs as 4 columns."""
    return len(s[: len(s) - len(s.lstrip(" \t"))].expandtabs(4))


def extract_python_symbols(text: str) -> list[dict[str, Any]]:
    """Top-level classes and functions of Python source with their line spans."""
    lines = text.split("\n")
    n = len(lines)
    decls: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        m = _PY_DECL_RE.match(ln)
        if not m:
            continue
        ind = _indent_width(m.group("ind"))
        start = i
        end = i
        j = i + 1
        while j < n:
            s = lines[j]
            if not s.strip():
                j += 1
                continue
            if _indent_width(s) > ind:
                end = j
                j += 1
                continue
            break
        decls.append(
            {
                "kind": "class" if m.group("kind") == "class" else "function",
                "name": m.group("name"),
                "indent": ind,
                "start": start,
                "end": end,
            }
        )
    classes = [d for d in decls if d["kind"] == "class"]
    symbols: list[dict[str, Any]] = []
    for d in decls:
        name, kind = d["name"], d["kind"]
        if d["indent"] > 0:
            enclosing = [
                c
                for c in classes
                if c["start"] < d["start"] <= c["end"] and c["indent"] < d["indent"]
            ]
            if enclosing:
                enclosing.sort(key=lambda c: c["indent"])
                name = f"{enclosing[-1]['name']}.{name}"
                kind = "method"
            else:
                continue
        symbols.append(
            {"symbol": name, "kind": kind, "line_start": d["start"] + 1, "line_end": d["end"] + 1}
        )
    return symbols


_BRACE_DECL_RES = [
    # Every modifier needs its own trailing whitespace: the old form only gave `default` one, so
    # `public class X` / `public interface X` / `private static final class X` never matched.
    re.compile(
        r"^[ \t]*(?:export[ \t]+)?(?:(?:public|private|protected|final|abstract|static|"
        r"sealed|non-sealed|default|internal|open|data)[ \t]+)*"
        r"(?P<kind>class|interface|struct|enum|record)[ \t]+(?P<name>[A-Za-z_]\w*)"
    ),
    re.compile(
        r"^[ \t]*(?:export[ \t]+)?(?:public|private|protected|static|async[ \t]+)*"
        r"\b(?:function|func|fn)\b[ \t]+(?P<name2>[A-Za-z_]\w*)"
    ),
    re.compile(
        r"^[ \t]*(?:export[ \t]+)?(?:const|let|var)[ \t]+(?P<name3>[A-Za-z_]\w*)[ \t]*="
        r"[ \t]*(?:async[ \t]+)?(?:function\b|\([^)]*\)[ \t]*=>|[A-Za-z_]\w*[ \t]*=>)"
    ),
]


def _brace_span(lines: list[str], start: int) -> int:
    """Index of the line where the brace block starting at ``start`` closes."""
    depth = 0
    seen = False
    for j in range(start, len(lines)):
        for ch in lines[j]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return j
        if not seen and lines[j].rstrip().endswith(";"):
            return j
    return start


def extract_brace_symbols(text: str) -> list[dict[str, Any]]:
    """Top-level declarations of brace-delimited languages with their line spans."""
    lines = text.split("\n")
    symbols: list[dict[str, Any]] = []
    for i, ln in enumerate(lines):
        for rex in _BRACE_DECL_RES:
            m = rex.match(ln)
            if not m:
                continue
            gd = m.groupdict()
            name = gd.get("name") or gd.get("name2") or gd.get("name3")
            if not name:
                continue
            symbols.append(
                {
                    "symbol": name,
                    "kind": gd.get("kind") or "function",
                    "line_start": i + 1,
                    "line_end": _brace_span(lines, i) + 1,
                }
            )
            break
    return symbols


# Java method: indented, at least one modifier, optional generic, a return type, then `name(`.
# Constructors (no return type) and modifier-less interface methods don't match by design.
_JAVA_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|final|synchronized|abstract|default|native)[ \t]+)+"
    r"(?:<[^>]*>[ \t]+)?[\w.$]+(?:<[^()]*?>)?(?:\[\])*[ \t]+(?P<name>[a-zA-Z_$][\w$]*)[ \t]*\("
)
_JAVA_NOT_METHODS = {"if", "for", "while", "switch", "catch", "return", "new", "throw", "else"}


def _has_body(lines: list[str], start: int) -> bool:
    """True when a `{` opens before any `;` — skips abstract / interface / native declarations."""
    for j in range(start, min(start + 12, len(lines))):
        for ch in lines[j]:
            if ch == "{":
                return True
            if ch == ";":
                return False
    return False


def extract_java_symbols(text: str) -> list[dict[str, Any]]:
    """Classes/interfaces/enums/records plus their methods, named `Class.method` like Python.
    Overloads keep one name each by appending `@<line>` from the second occurrence on."""
    lines = text.split("\n")
    classes = [s for s in extract_brace_symbols(text) if s["kind"] != "function"]
    symbols: list[dict[str, Any]] = list(classes)
    seen: dict[str, int] = {}
    for i, ln in enumerate(lines):
        m = _JAVA_METHOD_RE.match(ln)
        if not m or m.group("name") in _JAVA_NOT_METHODS or not _has_body(lines, i):
            continue
        line = i + 1
        enclosing = [c for c in classes if c["line_start"] < line <= c["line_end"]]
        owner = (
            min(enclosing, key=lambda c: c["line_end"] - c["line_start"])["symbol"]
            if enclosing
            else ""
        )
        name = f"{owner}.{m.group('name')}" if owner else m.group("name")
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}@{line}"
        symbols.append(
            {
                "symbol": name,
                "kind": "method",
                "line_start": line,
                "line_end": _brace_span(lines, i) + 1,
            }
        )
    symbols.sort(key=lambda s: s["line_start"])
    return symbols


def extract_symbols(text: str, language: str) -> list[dict[str, Any]]:
    """Symbols of ``text`` using the extractor for ``language``."""
    if language == "python":
        return extract_python_symbols(text)
    if language == "java":
        return extract_java_symbols(text)
    if language in BRACE_LANGS:
        return extract_brace_symbols(text)
    return []


# ---------------------------------------------------------------------------
# Imports → resolved edges
# ---------------------------------------------------------------------------
_PY_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+([A-Za-z_][\w.]*)", re.M)
_PY_FROM_RE = re.compile(r"^[ \t]*from[ \t]+(\.*)([A-Za-z_][\w.]*)?[ \t]+import\b", re.M)
_JS_IMPORT_RE = re.compile(r"""(?:import[^'"]*from|require[ \t]*\()[ \t]*['"]([^'"]+)['"]""")
_JAVA_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?([A-Za-z_][\w.]*)", re.M)


def extract_imports(text: str, language: str) -> list[str]:
    """Raw import / require / include specifiers found in ``text``."""
    if language == "python":
        out = list(_PY_IMPORT_RE.findall(text))
        for dots, mod in _PY_FROM_RE.findall(text):
            out.append(f"{dots}{mod or ''}")
        return out
    if language in ("javascript", "typescript"):
        return list(_JS_IMPORT_RE.findall(text))
    if language in ("java", "kotlin", "scala"):
        return list(_JAVA_IMPORT_RE.findall(text))
    return []


def _py_module_candidates(mod: str, current: str, path_set: set[str]) -> str | None:
    """Repo file that a Python module name or relative import refers to, if any."""
    if mod.startswith("."):
        base = posixpath.dirname(current)
        ups = len(mod) - len(mod.lstrip("."))
        for _ in range(ups - 1):
            base = posixpath.dirname(base)
        tail = mod.lstrip(".").replace(".", "/")
        stem = posixpath.join(base, tail) if tail else base
    else:
        stem = mod.replace(".", "/")
    for cand in (f"{stem}.py", f"{stem}/__init__.py"):
        cand = cand.lstrip("/")
        if cand in path_set:
            return cand
    if "/" in stem:
        parent = stem.rsplit("/", 1)[0]
        for cand in (f"{parent}.py", f"{parent}/__init__.py"):
            if cand in path_set:
                return cand
    return None


def _rel_js_candidates(spec: str, current: str, path_set: set[str]) -> str | None:
    """Repo file that a relative JS/TS import refers to, if any."""
    if not spec.startswith("."):
        return None
    base = posixpath.dirname(current)
    stem = posixpath.normpath(posixpath.join(base, spec)).lstrip("./")
    for e in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.js"):
        if f"{stem}{e}" in path_set:
            return f"{stem}{e}"
    return None


_JVM_PACKAGE_RE = re.compile(r"^[ \t]*package[ \t]+([A-Za-z_][\w.]*)", re.M)
_JVM_EXTS = (".java", ".kt", ".scala")


def build_jvm_index(files: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map each JVM file's fully-qualified name (its `package` + file stem) to its repo_path(s).

    Java imports name classes by package, not by path. Building the map from each file's own
    `package` line resolves imports under any source root (`<module>/src/main/java/...`,
    multi-module Maven/Gradle builds), which a path-only lookup can never match."""
    index: dict[str, list[str]] = {}
    for f in files:
        rp = f["repo_path"]
        if not rp.endswith(_JVM_EXTS):
            continue
        m = _JVM_PACKAGE_RE.search(f.get("text") or "")
        stem = posixpath.splitext(posixpath.basename(rp))[0]
        fqn = f"{m.group(1)}.{stem}" if m else stem
        index.setdefault(fqn, []).append(rp)
    return index


def _jvm_candidates(
    imp: str, current: str, path_set: set[str], jvm_index: dict[str, list[str]]
) -> list[str]:
    """Repo files that a Java/Kotlin/Scala import refers to, preferring the nearest module."""

    def pick(paths: list[str]) -> str:
        """The path sharing the longest prefix with the importing file."""
        # Same class name in several modules → prefer the one sharing the longest path prefix.
        return max(paths, key=lambda p: len(posixpath.commonprefix([p, current])))

    imp = imp.rstrip(".")
    if imp.endswith(".*") or imp.endswith("*"):
        imp = imp.rstrip("*").rstrip(".")
    # Wildcard / package import: every class in that package.
    pkg_hits = [pick(v) for k, v in jvm_index.items() if k.rsplit(".", 1)[0] == imp]
    if pkg_hits and imp not in jvm_index:
        return sorted(pkg_hits)
    # Class import; trim trailing segments for nested classes and static member imports.
    parts = imp.split(".")
    while parts:
        fqn = ".".join(parts)
        if fqn in jvm_index:
            return [pick(jvm_index[fqn])]
        stem = fqn.replace(".", "/")
        for ext in _JVM_EXTS:
            if f"{stem}{ext}" in path_set:
                return [f"{stem}{ext}"]
        parts.pop()
        if len(parts) < 2:
            break
    return []


def resolve_imports(
    imports: list[str],
    current: str,
    language: str,
    path_set: set[str],
    jvm_index: dict[str, list[str]] | None = None,
) -> list[str]:
    """Map raw import specifiers of one file to repo files."""
    resolved: list[str] = []
    for imp in imports:
        hits: list[str] = []
        if language == "python":
            hit = _py_module_candidates(imp, current, path_set)
            hits = [hit] if hit else []
        elif language in ("javascript", "typescript"):
            hit = _rel_js_candidates(imp, current, path_set)
            hits = [hit] if hit else []
        elif language in ("java", "kotlin", "scala"):
            hits = _jvm_candidates(imp, current, path_set, jvm_index or {})
        for hit in hits:
            if hit and hit != current and hit not in resolved:
                resolved.append(hit)
    return resolved


_JVM_NOISE_RE = re.compile(r"/\*.*?\*/|//[^\n]*|^[ \t]*(?:package|import)[ \t][^\n]*", re.S | re.M)
_FEIGN_RE = re.compile(r"@FeignClient\(\s*(?:name|value)\s*=\s*\"([\w-]+)\"")
_ROUTE_RE = re.compile(
    r"@(Get|Post|Put|Patch|Delete)Mapping(?:\(\s*(?:value\s*=\s*)?\"([^\"]*)\"[^)]*\)|\(\s*\)|)"
)
_BASE_ROUTE_RE = re.compile(r"@RequestMapping\(\s*(?:value\s*=\s*)?\"([^\"]*)\"")
_APP_NAME_RE = re.compile(r"application:\s*\n\s+name:\s*([\w-]+)")


def _service_root(repo_path: str) -> str:
    """The module a JVM file belongs to: everything before its `/src/` directory."""
    i = repo_path.find("/src/")
    return repo_path[:i] if i >= 0 else ""


def same_package_edges(files: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Edges to classes in the same package, which Java/Kotlin/Scala use without an import
    (fields, parameters, `extends`, `implements`, `new X()`). Only classes in the same module."""
    by_pkg: dict[str, dict[str, list[str]]] = {}
    pkg_of: dict[str, str] = {}
    for f in files:
        rp = f["repo_path"]
        if not rp.endswith(_JVM_EXTS):
            continue
        m = _JVM_PACKAGE_RE.search(f.get("text") or "")
        if not m:
            continue
        pkg_of[rp] = m.group(1)
        stem = posixpath.splitext(posixpath.basename(rp))[0]
        by_pkg.setdefault(m.group(1), {}).setdefault(stem, []).append(rp)
    edges: dict[str, list[str]] = {}
    for f in files:
        rp = f["repo_path"]
        if rp not in pkg_of:
            continue
        words = set(re.findall(r"[A-Za-z_]\w*", _JVM_NOISE_RE.sub("", f["text"])))
        for stem, paths in by_pkg[pkg_of[rp]].items():
            if stem not in words:
                continue
            for hit in paths:
                if hit != rp and _service_root(hit) == _service_root(rp):
                    edges.setdefault(rp, []).append(hit)
    return edges


def _jvm_routes(text: str) -> set[tuple[str, str]]:
    """(VERB, path) pairs from a Feign interface or a controller, `{var}` normalised to `{}`."""
    head, _, body = _JVM_NOISE_RE.sub("", text).partition("{")
    mb = _BASE_ROUTE_RE.search(head)
    base = mb.group(1) if mb else ""
    out: set[tuple[str, str]] = set()
    for m in _ROUTE_RE.finditer(body):
        full = "/" + "/".join(x for x in f"{base}/{m.group(2) or ''}".split("/") if x)
        out.add((m.group(1).upper(), re.sub(r"\{[^}]*\}", "{}", full)))
    return out


def feign_edges(files: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Edges from a `@FeignClient(name="x")` interface to the controller in service `x` that
    serves one of its routes. The service is the module whose application.yml has
    `spring.application.name: x`. These calls go over HTTP, so they have no import."""
    roots: dict[str, str] = {}
    for f in files:
        rp = f["repo_path"]
        if posixpath.basename(rp) in ("application.yml", "application.yaml"):
            m = _APP_NAME_RE.search(f["text"])
            if m:
                roots.setdefault(m.group(1).lower(), _service_root(rp))
    clients: list[tuple[str, str, set[tuple[str, str]]]] = []
    controllers: dict[str, list[tuple[str, set[tuple[str, str]]]]] = {}
    for f in files:
        rp, text = f["repo_path"], f["text"]
        if not rp.endswith((".java", ".kt")):
            continue
        m = _FEIGN_RE.search(text)
        if m:
            clients.append((rp, m.group(1).lower(), _jvm_routes(text)))
        elif "@RestController" in text or "@Controller" in text:
            controllers.setdefault(_service_root(rp), []).append((rp, _jvm_routes(text)))
    edges: dict[str, list[str]] = {}
    for rp, name, routes in clients:
        if name not in roots:
            continue
        for crp, croutes in controllers.get(roots[name], []):
            if routes & croutes:
                edges.setdefault(rp, []).append(crp)
    return edges


def build_manifest(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Symbols, resolved imports, modules and README map for the loaded files, plus Java same-
    package and Feign edges."""
    path_set = {f["repo_path"] for f in files}
    jvm_index = build_jvm_index(files)
    symbols: dict[str, list[dict[str, Any]]] = {}
    imports: dict[str, list[str]] = {}
    readmes: dict[str, str] = {}
    modules: dict[str, list[str]] = {}
    for f in files:
        rp, lang, text = f["repo_path"], f["language"], f["text"]
        modules.setdefault(module_of(rp), []).append(rp)
        if f.get("is_doc"):
            if posixpath.basename(rp).lower().startswith("readme"):
                readmes[module_of(rp)] = rp
            continue
        symbols[rp] = extract_symbols(text, lang)
        imports[rp] = resolve_imports(extract_imports(text, lang), rp, lang, path_set, jvm_index)
    for found in (same_package_edges(files), feign_edges(files)):
        for rp, hits in found.items():
            if rp in imports:
                imports[rp] = list(dict.fromkeys([*imports[rp], *hits]))
    return {
        "tree": sorted(path_set),
        "symbols": symbols,
        "imports": imports,
        "readmes": readmes,
        "modules": modules,
    }


def resolve_edges(manifest: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Invert the import map into ``depends_on`` / ``called_by`` lists per file."""
    imports = manifest["imports"]
    depends_on = {rp: sorted(set(deps)) for rp, deps in imports.items()}
    called_by: dict[str, set[str]] = {}
    for rp, deps in imports.items():
        for d in deps:
            called_by.setdefault(d, set()).add(rp)
    return {
        rp: {"depends_on": depends_on.get(rp, []), "called_by": sorted(called_by.get(rp, set()))}
        for rp in manifest["tree"]
    }


# ---------------------------------------------------------------------------
# Repo sources: URL parsing and safe archive unpacking
# ---------------------------------------------------------------------------
ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar")
MAX_UNPACK_BYTES = 200 * 1024 * 1024
MAX_UNPACK_FILES = 20_000
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
# Access tokens are only ever sent to these hosts (plus any in CODEWIKI_TOKEN_HOSTS, comma-separated),
# because the repo URL can come from an uploaded file and the token belongs to the server.
_DEFAULT_TOKEN_HOSTS = {"github.com", "api.github.com", "gitlab.com"}


class ArchiveError(RuntimeError):
    """An archive was rejected: unsafe path, size / file-count cap, or not a readable archive."""


def parse_repo_url(url: str) -> dict[str, str]:
    """Split a repo reference into parts.

    Returns ``kind`` ('git' or 'archive'), ``scheme``, ``url`` (canonical: no ``/tree/...``, no
    credentials, no query), ``fetch_url`` (archives only: the URL to download), ``host``, ``owner``,
    ``repo``, ``ref`` and ``subdir`` (from ``/tree/<ref>/<subdir>``; a ref containing '/' is not
    supported). Anything that doesn't parse comes back unchanged in ``url``.
    """
    raw = (url or "").strip()
    out = {
        "kind": "git",
        "scheme": "",
        "url": raw,
        "fetch_url": "",
        "host": "",
        "owner": "",
        "repo": "",
        "ref": "",
        "subdir": "",
    }
    m = re.match(r"^(?:ssh://)?git@([\w.\-]+)[:/]([^/\s]+)/(\S+?)(?:\.git)?/?$", raw)
    if m:
        out.update(scheme="ssh", host=m.group(1).lower(), owner=m.group(2), repo=m.group(3))
        return out
    try:
        sp = urlsplit(raw)
        port = sp.port
    except ValueError:
        return out
    if sp.scheme not in ("http", "https") or not sp.hostname:
        return out
    host = sp.hostname.lower()
    netloc = host + (f":{port}" if port else "")
    out.update(scheme=sp.scheme, host=host)
    if sp.path.lower().endswith(ARCHIVE_SUFFIXES):
        fetch = f"{sp.scheme}://{netloc}{sp.path}" + (f"?{sp.query}" if sp.query else "")
        out.update(kind="archive", url=f"{sp.scheme}://{netloc}{sp.path}", fetch_url=fetch)
        return out
    parts = [p for p in sp.path.split("/") if p]
    if "-" in parts:  # GitLab: <group>/<project>/-/tree/<ref>/<subdir>
        i = parts.index("-")
        project, rest = parts[:i], parts[i + 1 :]
    else:
        project, rest = parts[:2], parts[2:]
    if len(project) < 2:
        return out
    owner, repo = "/".join(project[:-1]), re.sub(r"\.git$", "", project[-1])
    out.update(owner=owner, repo=repo, url=f"{sp.scheme}://{netloc}/{owner}/{repo}")
    if len(rest) >= 2 and rest[0] in ("tree", "blob"):
        out.update(ref=rest[1], subdir="/".join(rest[2:]))
    return out


def host_kind(host: str) -> str:
    """'github' / 'gitlab' for github.com, github.<corp>.com, gitlab.com ... else ''."""
    labels = (host or "").lower().split(".")
    if "gitlab" in labels:
        return "gitlab"
    if "github" in labels:
        return "github"
    return ""


def token_allowed(host: str) -> bool:
    """True if the access token may be sent to ``host`` (default hosts plus
    ``CODEWIKI_TOKEN_HOSTS``)."""
    extra = {
        h.strip().lower()
        for h in os.environ.get("CODEWIKI_TOKEN_HOSTS", "").split(",")
        if h.strip()
    }
    return (host or "").lower() in (_DEFAULT_TOKEN_HOSTS | extra)


def _safe_member_path(name: str) -> str:
    """Normalise an archive entry name; reject absolute paths and '..' (zip-slip)."""
    n = (name or "").replace("\\", "/")
    if "\x00" in n or n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        raise ArchiveError(f"unsafe path in archive: {name!r}")
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ArchiveError(f"unsafe path in archive: {name!r}")
    return "/".join(parts)


def _common_root(rels: list[str]) -> str:
    """The single top-level directory that wraps every file (GitHub tarballs), else ''."""
    firsts = {r.split("/", 1)[0] for r in rels}
    if len(firsts) == 1 and all("/" in r for r in rels):
        return firsts.pop()
    return ""


def _wanted_member(rel: str, size: int, prefix: str) -> bool:
    """Same filters as walk_files, applied up front so ignored trees never count against the caps."""
    inner = rel[len(prefix) + 1 :] if prefix else rel
    if any(is_ignored_dir(p) for p in inner.split("/")[:-1]) or is_ignored_file(inner):
        return False
    return size <= MAX_FILE_BYTES


def _write_capped(src, target: str, used: int, max_bytes: int) -> int:
    """Copy ``src`` to ``target``, raising once the archive's running total passes ``max_bytes``."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as out:
        while chunk := src.read(65536):
            used += len(chunk)
            if used > max_bytes:
                raise ArchiveError(
                    f"archive expands beyond the {max_bytes // (1024 * 1024)} MB limit"
                )
            out.write(chunk)
    return used


def unpack_archive(
    path: str, dest: str, max_bytes: int = MAX_UNPACK_BYTES, max_files: int = MAX_UNPACK_FILES
) -> str:
    """Safely unpack a .zip / .tar / .tar.gz / .tgz (detected by content, not by name) into ``dest``.

    Every entry name is validated before anything is written: absolute paths and '..' raise
    ``ArchiveError``. Symlinks, hard links and devices are skipped. Only files the walker would
    keep are written, and the bytes actually written and the file count are capped. Returns the
    repo root (the single wrapping directory if there is one, else ``dest``).
    """
    dest_real = os.path.realpath(dest)
    os.makedirs(dest_real, exist_ok=True)
    declared_limit = max_bytes * 10  # stops a bomb from being scanned forever
    members: list[tuple[str, int, Any]] = []
    declared = 0
    if zipfile.is_zipfile(path):
        archive = zipfile.ZipFile(path)
        opener = archive.open
        for info in archive.infolist():
            rel = _safe_member_path(info.filename)
            if not rel or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                continue
            declared += info.file_size
            members.append((rel, info.file_size, info))
    elif tarfile.is_tarfile(path):
        archive = tarfile.open(path, "r:*")
        opener = archive.extractfile
        for m in archive:
            rel = _safe_member_path(m.name)
            if not rel or not m.isfile():  # skips dirs, symlinks, hard links, devices
                continue
            declared += m.size
            if declared > declared_limit:
                break
            members.append((rel, m.size, m))
    else:
        raise ArchiveError("not a zip or tar archive")
    try:
        if declared > declared_limit:
            raise ArchiveError(
                f"archive is far larger than the {max_bytes // (1024 * 1024)} MB limit"
            )
        prefix = _common_root([r for r, _, _ in members])
        used = count = 0
        for rel, size, member in members:
            if not _wanted_member(rel, size, prefix):
                continue
            count += 1
            if count > max_files:
                raise ArchiveError(f"archive has more than {max_files} source files")
            target = os.path.join(dest_real, *rel.split("/"))
            if os.path.commonpath([dest_real, os.path.realpath(target)]) != dest_real:
                raise ArchiveError(f"unsafe path in archive: {rel!r}")
            src = opener(member)
            if src is None:
                continue
            with src:
                used = _write_capped(src, target, used, max_bytes)
    finally:
        archive.close()
    return os.path.join(dest_real, prefix) if prefix else dest_real


def _display_url(url: str) -> str:
    """URL without credentials or query string, for messages (signed URLs carry secrets)."""
    sp = urlsplit(url)
    return f"{sp.scheme}://{sp.hostname or ''}{sp.path}"


def _private_hosts_allowed() -> bool:
    """True when CODEWIKI_ALLOW_PRIVATE_HOSTS opts in to internal hosts and plain http."""
    return os.environ.get("CODEWIKI_ALLOW_PRIVATE_HOSTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _assert_public_host(host: str, port: int | None = None) -> None:
    """Refuse a host that resolves to any private, loopback or link-local address (the URL can
    come from an uploaded file, so the server must not be pointed at internal services). Set
    CODEWIKI_ALLOW_PRIVATE_HOSTS=1 to allow internal hosts."""
    if _private_hosts_allowed():
        return
    if not host:
        raise RuntimeError("repo URL has no host")
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, port or 443)}
    except OSError as e:
        raise RuntimeError(f"cannot resolve host {host!r}") from e
    if not addrs or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs):
        raise RuntimeError(
            f"host {host!r} is not a public address (set CODEWIKI_ALLOW_PRIVATE_HOSTS=1 "
            "to allow internal hosts)"
        )


def _assert_public_https(url: str) -> None:
    """Refuse non-https URLs and hosts that resolve to non-public addresses (see
    ``_assert_public_host``)."""
    sp = urlsplit(url)
    if sp.scheme != "https" or not sp.hostname:
        raise RuntimeError("only https:// archive URLs are allowed")
    _assert_public_host(sp.hostname, sp.port)


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------
def _env_fallback(value: str, *env_names: str, default: str = "") -> str:
    """Return ``value`` unless it is empty or an unresolved global-variable name; otherwise the
    first set env var, else ``default``."""
    v = (value or "").strip()
    # An unresolved global var may literally read its own upper-case name (e.g. "REPO_URL").
    if v and not (v.replace("_", "").isalpha() and v.isupper() and " " not in v):
        return v
    for name in env_names:
        got = os.environ.get(name)
        if got:
            return got
    return default


class RepoLoader(Component):
    """Langflow component that loads a repo (git, archive or local path) and builds its manifest and
    edges."""

    display_name = "Repo Loader"
    description = (
        "Clone a git repo (or read a local path), walk it with ignore rules, and build a "
        "manifest (symbols+line spans, resolved import graph). No LLM."
    )
    icon = "GitBranch"
    name = "RepoLoader"

    inputs = [
        HandleInput(
            name="pointer_data",
            display_name="Repo URL source",
            input_types=["Data", "DataFrame", "Table", "JSON", "Message"],
            required=False,
            info="Optional. Parsed text of an uploaded pointer file whose content is the git "
            "URL (Knowledge-UI ingestion). Supports optional 'ref:'/'subtree:' lines. "
            "Takes precedence over the repo_url field / REPO_URL global.",
        ),
        StrInput(
            name="repo_url",
            display_name="Git repo URL",
            value="REPO_URL",
            load_from_db=True,
            info="e.g. https://github.com/owner/repo, https://github.com/owner/repo/tree/main/src, "
            "git@github.com:owner/repo.git, or a direct .zip / .tar.gz URL. Bound to the "
            "REPO_URL global; can be set per run with a tweak. Ignored if a local path is given.",
        ),
        StrInput(
            name="repo_ref",
            display_name="Branch / ref",
            value="",
            advanced=True,
            info="Branch or tag to clone (default: the repo's default branch).",
        ),
        StrInput(
            name="local_path",
            display_name="Local path",
            value="",
            advanced=True,
            info="Absolute path to a repo already on disk, or to a .zip / .tar.gz of one (skips "
            "git clone). Falls back to env CODEWIKI_LOCAL_PATH.",
        ),
        StrInput(
            name="subtree",
            display_name="Subtree scope",
            value="",
            advanced=True,
            info="Comma-separated repo-relative prefixes to scope ingestion (large repos), e.g. "
            "src/pkg,src/main.py . Empty = whole repo.",
        ),
        IntInput(
            name="max_files",
            display_name="Max files",
            value=0,
            advanced=True,
            info="Cap on files ingested (0 = no cap). Guardrail for very large repos.",
        ),
        IntInput(
            name="clone_depth",
            display_name="Clone depth",
            value=1,
            advanced=True,
            info="git clone --depth (shallow clone; 1 = latest commit only).",
        ),
        SecretStrInput(
            name="access_token",
            display_name="Access token",
            value="",
            advanced=True,
            info="Token for private repos (GitHub / GitLab). Falls back to env GITHUB_TOKEN, "
            "GH_TOKEN or GITLAB_TOKEN. Only sent to github.com, gitlab.com and hosts "
            "listed in env CODEWIKI_TOKEN_HOSTS (comma-separated).",
        ),
        # Knowledge-UI upload path: the OpenRAG backend sends the uploaded file to Docling Serve,
        # waits for the conversion, then runs this flow with the Docling task id in the
        # DOCLING_TASK_ID global. RepoLoader fetches that converted text itself (no Docling nodes in
        # the graph — Langflow builds every node, and DoclingRemote fails without a file).
        StrInput(
            name="docling_task_id",
            display_name="Docling task ID",
            value="DOCLING_TASK_ID",
            load_from_db=True,
            advanced=True,
            info="Set per upload by the OpenRAG backend. The converted pointer file's text "
            "(git URL + optional ref:/subtree: lines) takes precedence over repo_url.",
        ),
        StrInput(
            name="docling_url",
            display_name="Docling Serve URL",
            value="DOCLING_SERVE_URL",
            load_from_db=True,
            advanced=True,
            info="Docling Serve base URL (DOCLING_SERVE_URL global, injected by the backend).",
        ),
        StrInput(
            name="docling_auth",
            display_name="Docling Authorization",
            value="JWT",
            load_from_db=True,
            advanced=True,
            info="Authorization header for Docling Serve (JWT global, injected by the backend; "
            "empty locally).",
        ),
        StrInput(
            name="docling_verify_ssl",
            display_name="Docling verify SSL",
            value="DOCLING_SERVE_VERIFY_SSL",
            load_from_db=True,
            advanced=True,
        ),
    ]

    outputs = [Output(display_name="Repo", name="repo_out", method="load_repo")]

    def _notify(self, msg: str) -> None:
        """Set the component status and log ``msg``; logging errors are ignored."""
        self.status = msg
        try:
            self.log(msg)
        except Exception:  # noqa: BLE001
            pass

    _GIT_HTTP_RE = re.compile(r"https?://[^\s'\"<>)\]]+")
    _GIT_SSH_RE = re.compile(r"git@[\w.\-]+:[\w./\-]+")

    @staticmethod
    def _coalesce_text(obj) -> str:
        """Flatten a DataFrame / Data / Message / list handed in on the pointer input into raw text."""
        try:
            import pandas as pd
        except Exception:  # noqa: BLE001
            pd = None
        parts: list = []

        def add(x) -> None:
            """Append a string, or the strings of a list, to the collected parts."""
            if x is None:
                return
            if isinstance(x, str):
                parts.append(x)
                return
            if isinstance(x, (list, tuple)):
                for i in x:
                    add(i)
                return
            if pd is not None and isinstance(x, pd.DataFrame):
                for col in x.columns:
                    for v in x[col].tolist():
                        if isinstance(v, str):
                            parts.append(v)
                return
            for attr in ("text", "get_text"):
                if hasattr(x, attr):
                    try:
                        val = getattr(x, attr)
                        val = val() if callable(val) else val
                        if isinstance(val, str) and val.strip():
                            parts.append(val)
                            return
                    except Exception:  # noqa: BLE001
                        pass
            dd = getattr(x, "data", None)
            if isinstance(dd, dict):
                for v in dd.values():
                    if isinstance(v, str):
                        parts.append(v)
                return
            parts.append(str(x))

        add(obj)
        return "\n".join(p for p in parts if p and p.strip())

    @staticmethod
    def _global_value(value) -> str:
        """Resolve a load_from_db field: a still-unresolved global name, 'None' or empty → ''."""
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        s = str(value or "").strip()
        if not s or s.lower() == "none" or (s.replace("_", "").isupper() and " " not in s):
            return ""
        return s

    def _docling_pointer_text(self) -> str:
        """Fetch the uploaded file's converted text from Docling Serve via the backend's task id.
        Returns '' when there is no task (CLI runs) so those paths are unchanged."""
        task_id = self._global_value(getattr(self, "docling_task_id", ""))
        base = self._global_value(getattr(self, "docling_url", "")) or os.environ.get(
            "DOCLING_SERVE_URL", ""
        )
        if not task_id or not base:
            return ""
        import httpx  # bundled in the Langflow image

        base = base.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        headers = {}
        auth = self._global_value(getattr(self, "docling_auth", ""))
        if auth:
            headers["Authorization"] = auth
        verify = self._global_value(getattr(self, "docling_verify_ssl", "")).lower() not in (
            "false",
            "0",
            "no",
        )
        try:
            with httpx.Client(headers=headers, verify=verify, timeout=60) as client:
                resp = client.get(f"{base}/result/{task_id}")
                resp.raise_for_status()
                payload = resp.json() or {}
                doc = payload.get("document") or {}
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Could not fetch the uploaded pointer file from Docling (task {task_id}): {e}"
            ) from e
        # Docling reports a task as successful even when it refused the file (archives and source
        # code come back 'skipped' with 'File format not allowed' and no content at all).
        errors = [
            str(e.get("error_message") or e) if isinstance(e, dict) else str(e)
            for e in payload.get("errors") or []
        ]
        if payload.get("status") in ("skipped", "failure") or errors:
            name = doc.get("filename") or "the uploaded file"
            why = "; ".join(errors)[:300] or str(payload.get("status"))
            self._docling_error = f"Docling did not convert {name} ({why})."
            self._notify(self._docling_error)
            return ""
        text = doc.get("md_content") or doc.get("text_content") or ""
        if not text.strip():
            # The OpenRAG backend requests JSON only, so the text lives in the DoclingDocument's
            # `texts` items (one per paragraph) instead of md_content.
            jc = doc.get("json_content")
            if isinstance(jc, str):
                try:
                    import json as _json

                    jc = _json.loads(jc)
                except ValueError:
                    jc = None
            if isinstance(jc, dict):
                text = "\n".join(
                    (t.get("text") or t.get("orig") or "").strip()
                    for t in jc.get("texts") or []
                    if isinstance(t, dict)
                )
        # Docling renders a bare URL as a markdown link "[url](url)"; keep the URL itself.
        text = re.sub(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", r"\2", text)
        self._pointer_chars = len(text)
        self._notify(f"Docling task {task_id}: {len(text)} chars of pointer text")
        return text

    @staticmethod
    def _split_pointer_lines(text: str) -> str:
        """Docling joins a plain-text file's lines into one paragraph; re-break before the
        'ref:'/'branch:'/'subtree:'/'repo:'/'url:' keys so each is parsed on its own line."""
        return re.sub(r"\s+(?=(?:ref|branch|subtree|repo|url):)", "\n", text, flags=re.I)

    def _parse_pointer(self) -> tuple:
        """Extract (url, ref, subtree) from the uploaded pointer file's text — from a wired
        pointer_data input, else from the backend's Docling task. Returns empties when neither is
        present (e.g. a run that sets repo_url directly) so that path is entirely unchanged."""
        text = self._coalesce_text(getattr(self, "pointer_data", None))
        if not text or not text.strip():
            text = self._docling_pointer_text()
        if not text or not text.strip():
            return "", "", ""
        text = self._split_pointer_lines(text)
        url = ref = subtree = ""
        for line in text.splitlines():
            s = line.strip()
            low = s.lower()
            if low.startswith(("ref:", "branch:")):
                ref = s.split(":", 1)[1].strip()
            elif low.startswith("subtree:"):
                subtree = s.split(":", 1)[1].strip()
            elif low.startswith(("repo:", "url:")):
                cand = s.split(":", 1)[1].strip()
                if cand:
                    url = cand
        if not url:
            m = self._GIT_HTTP_RE.search(text) or self._GIT_SSH_RE.search(text)
            if m:
                url = m.group(0)
        url = url.strip().rstrip(".,;)")
        self._notify(
            f"Pointer URL: {url or '(none found)'}"
            + (f" ref={ref}" if ref else "")
            + (f" subtree={subtree}" if subtree else "")
        )
        return url, ref, subtree

    def _no_source_message(self) -> str:
        """Error text explaining that no repo source was provided and how to supply one."""
        docling_err = getattr(self, "_docling_error", "")
        if docling_err:
            head = (
                f"{docling_err} Docling can't convert archives or source code, so a zip or source "
                "file uploaded in the Knowledge UI never reaches RepoLoader. Upload a pointer .txt "
                "file containing the repo URL, or set 'repo_url' / 'local_path'. "
            )
        else:
            head = (
                "No repo source: upload a pointer file containing a git URL, or set 'repo_url' "
                "(or the REPO_URL global) / 'local_path'. "
            )
        has_pointer = bool(self._coalesce_text(getattr(self, "pointer_data", None)).strip())
        return (
            head + "Tried: pointer_data input, Docling pointer text, repo_url / REPO_URL, "
            "local_path / CODEWIKI_LOCAL_PATH. Seen: "
            f"pointer_data={'yes' if has_pointer else 'empty'}, "
            f"docling_task_id={self._global_value(getattr(self, 'docling_task_id', '')) or 'missing'}, "
            f"docling_url={self._global_value(getattr(self, 'docling_url', '')) or 'missing'}, "
            f"pointer_text_chars={getattr(self, '_pointer_chars', 0)}. A run started from the "
            "Langflow playground has no upload, so it always needs repo_url."
        )

    def _resolve_token(self, host: str) -> str:
        """The access token to send to ``host`` ('' if none, or if the host isn't trusted with it)."""
        if not token_allowed(host):
            return ""
        tok = getattr(self, "access_token", "")
        if hasattr(tok, "get_secret_value"):
            tok = tok.get_secret_value()
        tok = (tok or "").strip()
        if tok:
            return tok
        names = ("GITLAB_TOKEN",) if host_kind(host) == "gitlab" else ("GITHUB_TOKEN", "GH_TOKEN")
        for name in names:
            got = os.environ.get(name, "").strip()
            if got:
                return got
        return ""

    @staticmethod
    def _scrub(text: str, *secrets: str) -> str:
        """Replace each secret, raw and base64-encoded, with ``***``."""
        for sec in secrets:
            if sec:
                text = text.replace(sec, "***")
                text = text.replace(base64.b64encode(sec.encode()).decode(), "***")
        return text

    @staticmethod
    def _git_env(host: str, scheme: str, token: str) -> dict[str, str]:
        """Environment for ``git clone``: no prompts, restricted transports, no HTTP redirects,
        symlinks checked out as plain files, and (https only) the access token as an HTTP header."""
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        # Block ext:: / file:: transports: the URL can come from an uploaded file. Plain http is
        # allowed only with the same opt-in as internal hosts.
        env["GIT_ALLOW_PROTOCOL"] = "https:http:ssh" if _private_hosts_allowed() else "https:ssh"
        # followRedirects=false: the host was checked above, but a redirect could send the clone
        # (and the token header) to an internal host that was never checked.
        config = [("core.symlinks", "false"), ("http.followRedirects", "false")]
        if token and scheme == "https":
            # Passed through the environment, not argv or the clone URL, so it isn't visible in the
            # process list and isn't written to the clone's .git/config. Never sent over http.
            user = "oauth2" if host_kind(host) == "gitlab" else "x-access-token"
            basic = base64.b64encode(f"{user}:{token}".encode()).decode()
            config.append(("http.extraHeader", f"Authorization: Basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(config))
        for i, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        return env

    def _new_temp_dir(self) -> str:
        """Create a ``codewiki_*`` work directory. ``load_repo`` deletes it after reading."""
        tmp = tempfile.mkdtemp(prefix="codewiki_")
        owned = getattr(self, "_temp_dirs", None)
        if owned is None:
            owned = []
            self._temp_dirs = owned
        owned.append(tmp)
        return tmp

    def _cleanup_temp_dirs(self) -> None:
        """Delete every temp directory this loader created."""
        for tmp in getattr(self, "_temp_dirs", None) or []:
            shutil.rmtree(tmp, ignore_errors=True)
        self._temp_dirs = []

    def _unpack_to_temp(self, archive_path: str) -> str:
        """Unpack an archive into a new temp directory and return the source root."""
        tmp = self._new_temp_dir()
        try:
            return unpack_archive(archive_path, os.path.join(tmp, "src"))
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _obtain_repo(
        self, pointer_url: str = "", pointer_ref: str = ""
    ) -> tuple[str, str, str, str]:
        """Return (root_dir, repo_url, repo_ref, url_subdir). First source found wins: a local
        directory, a local .zip/.tar.gz, then the repo URL (a URL parsed from an uploaded pointer
        file wins over the repo_url field/global): a direct archive URL, a git clone, or, when the
        ``git`` binary is missing (the hosted Langflow image), an HTTPS tarball download.
        ``url_subdir`` is the directory from a ``/tree/<ref>/<subdir>`` URL ('' otherwise)."""
        ref_in = (pointer_ref or getattr(self, "repo_ref", "") or "").strip()
        local = _env_fallback(getattr(self, "local_path", ""), "CODEWIKI_LOCAL_PATH")
        if local and Path(local).is_dir():
            self._notify(f"Using local path {local}")
            return local, "", ref_in, ""
        if local and Path(local).is_file():
            self._notify(f"Unpacking local archive {Path(local).name}")
            try:
                return self._unpack_to_temp(local), "", ref_in, ""
            except ArchiveError as e:
                raise ArchiveError(f"local_path {Path(local).name!r} is not usable: {e}") from e

        repo_url = pointer_url or _env_fallback(
            getattr(self, "repo_url", ""), "REPO_URL", "CODEWIKI_REPO_URL"
        )
        if not repo_url:
            raise ValueError(self._no_source_message())

        info = parse_repo_url(repo_url)
        url, host, scheme = info["url"], info["host"], info["scheme"]
        # The token is only ever sent over https.
        token = self._resolve_token(host) if scheme == "https" else ""
        if info["kind"] == "archive":
            return self._download_archive_url(info, token), url, ref_in, ""
        if scheme not in ("http", "https", "ssh"):
            raise ValueError(
                f"Unsupported repo URL {repo_url!r}: use an https:// URL, git@host:owner/repo, or "
                "a direct .zip / .tar.gz URL, or set 'local_path'."
            )
        if scheme == "http" and not _private_hosts_allowed():
            raise ValueError(
                f"Plain http repo URLs are not allowed ({_display_url(url)}): use https:// "
                "(set CODEWIKI_ALLOW_PRIVATE_HOSTS=1 to allow http for internal git servers)."
            )
        # The URL can come from an uploaded pointer file: don't let it reach internal hosts.
        _assert_public_host(host)
        ref = ref_in or info["ref"]
        subdir = info["subdir"]

        # No git binary (e.g. the hosted Langflow image) → fetch the repo archive over HTTPS instead.
        if not shutil.which("git"):
            return self._download_tarball(info, ref, token), url, ref, subdir

        depth = max(1, int(getattr(self, "clone_depth", 1) or 1))
        tmp = self._new_temp_dir()
        cmd = ["git", "clone", "--depth", str(depth), "--single-branch"]
        if ref:
            cmd += ["--branch", ref]
        cmd += ["--", url, tmp]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
                env=self._git_env(host, scheme, token),
            )
        except FileNotFoundError:  # git disappeared between the which() check and the call
            shutil.rmtree(tmp, ignore_errors=True)
            return self._download_tarball(info, ref, token), url, ref, subdir
        except subprocess.CalledProcessError as e:
            shutil.rmtree(tmp, ignore_errors=True)
            detail = self._scrub((e.stderr or e.stdout or "").strip()[:400], token)
            hint = "" if token else " If the repo is private, set 'Access token'."
            raise RuntimeError(f"git clone failed: {detail}{hint}") from e
        return tmp, url, ref, subdir

    def _fetch(self, url: str, headers: dict[str, str], dest: str, *, guard: bool) -> None:
        """Download ``url`` to ``dest`` (capped at MAX_DOWNLOAD_BYTES). With ``guard`` the URL must
        be https and resolve to public addresses, checked again on every redirect hop."""
        import httpx  # bundled in the Langflow image

        hops = 0
        headers = dict(headers)
        with httpx.Client(timeout=600, follow_redirects=not guard) as client:
            while True:
                if guard:
                    _assert_public_https(url)
                with client.stream("GET", url, headers=headers) as resp:
                    if guard and resp.status_code in (301, 302, 303, 307, 308):
                        hops += 1
                        loc = resp.headers.get("location", "")
                        if not loc or hops > 5:
                            raise RuntimeError("too many or invalid redirects")
                        nxt = urljoin(url, loc)
                        if urlsplit(nxt).netloc != urlsplit(url).netloc:
                            headers.pop("Authorization", None)
                        url = nxt
                        continue
                    if resp.status_code >= 400:
                        resp.read()
                        raise RuntimeError(f"HTTP {resp.status_code} for {_display_url(url)}")
                    size = 0
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_bytes():
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise RuntimeError(
                                    f"download is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB"
                                )
                            fh.write(chunk)
                    return

    def _download_and_unpack(
        self, archive_url: str, headers: dict[str, str], *, guard: bool, label: str
    ) -> str:
        """Download an archive into a temp directory and unpack it; the temp directory is removed on
        failure."""
        tmp = self._new_temp_dir()
        path = os.path.join(tmp, "download")
        try:
            try:
                self._fetch(archive_url, headers, path, guard=guard)
            except Exception as e:
                raise RuntimeError(f"archive download failed ({label}): {str(e)[:300]}") from e
            root = unpack_archive(path, os.path.join(tmp, "src"))
            os.remove(path)
            return root
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _download_archive_url(self, info: dict[str, str], token: str) -> str:
        """Fetch a direct .zip / .tar.gz URL and unpack it safely."""
        if info["scheme"] != "https":
            raise ValueError("Archive URLs must use https://")
        headers = {"User-Agent": "openrag-codewiki"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._notify(f"Downloading archive from {_display_url(info['fetch_url'])}…")
        return self._download_and_unpack(
            info["fetch_url"], headers, guard=True, label=_display_url(info["fetch_url"])
        )

    def _download_tarball(self, info: dict[str, str], ref: str, token: str) -> str:
        """Git-less repo acquisition: download the repo as a tarball over HTTPS and unpack it,
        returning the repo root. Supports GitHub (github.com and Enterprise) and GitLab, public or
        private. Raises with a clear message for unsupported hosts."""
        host, owner, repo = info["host"], info["owner"], info["repo"]
        kind = host_kind(host)
        headers = {"User-Agent": "openrag-codewiki"}
        if kind == "github":
            api = (
                "https://api.github.com"
                if host in ("github.com", "www.github.com")
                else (f"https://{host}/api/v3")
            )
            archive_url = f"{api}/repos/{owner}/{repo}/tarball" + (
                f"/{quote(ref, safe='/')}" if ref else ""
            )
            headers["Accept"] = "application/vnd.github+json"
        elif kind == "gitlab":
            pid = quote(f"{owner}/{repo}", safe="")
            archive_url = f"https://{host}/api/v4/projects/{pid}/repository/archive.tar.gz" + (
                f"?sha={quote(ref, safe='')}" if ref else ""
            )
        else:
            raise RuntimeError(
                f"git is unavailable and host '{host}' is not a supported archive host "
                "(GitHub or GitLab). Install git, give a direct .zip / .tar.gz URL, or mount the "
                "repo (local_path)."
            )
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._notify(
            f"git unavailable; downloading {host} archive for {owner}/{repo}"
            f"{('@' + ref) if ref else ''}…"
        )
        # guard=True: https only, public hosts only, checked again on every redirect hop. A host
        # name with a "github"/"gitlab" label can still be an internal server.
        return self._download_and_unpack(
            archive_url, headers, guard=True, label=f"{owner}/{repo}@{ref or 'default'}"
        )

    def load_repo(self) -> Data:
        """Obtain the repo, read its files into memory, and build the manifest and edges. Any
        clone or unpack directory created on the way is deleted before returning (a user-supplied
        ``local_path`` directory is never touched)."""
        pointer_url, pointer_ref, pointer_subtree = self._parse_pointer()
        try:
            root, repo_url, repo_ref, url_subdir = self._obtain_repo(pointer_url, pointer_ref)
            subtree_src = pointer_subtree or (getattr(self, "subtree", "") or "") or url_subdir
            subtrees = [s.strip() for s in subtree_src.split(",") if s.strip()]
            files = walk_files(root, subtrees, int(getattr(self, "max_files", 0) or 0))
        finally:
            self._cleanup_temp_dirs()
        if not files:
            raise RuntimeError(
                f"RepoLoader found 0 ingestible files under {root} "
                f"(subtree={subtrees or 'whole repo'}). Check the URL/branch/subtree."
            )
        manifest = build_manifest(files)
        edges = resolve_edges(manifest)
        n_sym = sum(len(v) for v in manifest["symbols"].values())
        self._notify(
            f"Loaded {len(files)} file(s), {len([m for m in manifest['modules'] if m])} "
            f"module(s), {n_sym} symbol(s) from {repo_url or root}"
        )
        return Data(
            data={
                "repo": {
                    "files": files,
                    "manifest": manifest,
                    "edges": edges,
                    "repo_url": repo_url,
                    "repo_ref": repo_ref,
                }
            }
        )
