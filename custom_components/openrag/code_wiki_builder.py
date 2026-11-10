"""Langflow custom component: CodeWikiBuilder (LLM structuring → OpenSearch docs).

Consumes the whole-repo payload from ``RepoLoader`` and turns it into wiki pages:
- one **overview** page (repo architecture + module index),
- one **module page** per package/folder,
- one **file page** per source file, and
- one **symbol page** per top-level class/function in LARGE files (so retrieval can land on
  ``ServiceRegistry.async_register`` directly), plus **doc pages** for README/*.md.

Each page is Markdown body + YAML frontmatter with a ``# [<repo_path>] <title>`` header. The LLM
writes the human summary/body; because the manifest already carries EXACT line spans and RESOLVED
dependency edges, the page metadata (``wiki_symbols`` with ``line_start``/``line_end``,
``wiki_depends_on``/``wiki_called_by``) is deterministic — the model is told to cite those spans, not
invent them. If the model fails or is slow, the page falls back to a deterministic body so ingestion
never breaks.

Pages chunk losslessly into OpenSearch docs (all custom provenance fields are stored top-level; the
stock search tool's 13-field allow-list is why the chat flow needs a custom ``search_wiki``).

Wire it: ``RepoLoader → repo_data``; a Language Model → ``model``; ``CodeWikiBuilder → OpenSearch.ingest_data``.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from lfx.custom.custom_component.component import Component
from lfx.io import BoolInput, HandleInput, IntInput, Output
from lfx.schema.data import Data

# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------
_WIKI_SYSTEM = """You are a senior engineer writing a CODE WIKI page for one part of a repository. \
You are given structured, ALREADY-EXTRACTED facts (symbols with exact line spans, resolved dependency \
edges, and source) as JSON. Write a clear, faithful wiki page.

Return ONLY a JSON object: {"summary": string, "body": string}.
- "summary": ONE sentence (<=200 chars) — what this file/module/symbol IS and does. Used for retrieval.
- "body": GitHub-flavoured Markdown explaining it for a developer asking "how do I use this?". \
Sections as appropriate: Purpose, Key APIs / Signature, How to use (a short realistic snippet), \
Notable logic, Related.

RULES:
- Be faithful to the provided facts and source. NEVER invent functions, parameters, or files that are \
not present. If unsure, say less.
- CITE code locations as `repo_path:line_start-line_end` using ONLY the spans given in the facts \
(e.g. `src/pkg/module.py:10-42`). Do not guess line numbers.
- Refer to dependencies/callers by their real repo_path from the edges provided.
- Do not repeat the raw source verbatim at length; explain it. Keep it tight and practical."""


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    frag = text[start:]
    for end in range(len(frag) - 1, 0, -1):
        if frag[end] == "}":
            try:
                return json.loads(frag[: end + 1])
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("could not repair JSON", text, 0)


# ---------------------------------------------------------------------------
# Rendering + chunking
# ---------------------------------------------------------------------------
def module_of(repo_path: str) -> str:
    return posixpath.dirname(repo_path)


def chunk_fragments(md: str, size: int) -> list[str]:
    if size <= 0 or len(md) <= size:
        return [md]
    frags: list[str] = []
    cur = ""
    for ln in md.splitlines(keepends=True):
        if cur and len(cur) + len(ln) > size:
            frags.append(cur)
            cur = ""
        if len(ln) > size:
            if cur:
                frags.append(cur)
                cur = ""
            for i in range(0, len(ln), size):
                frags.append(ln[i : i + size])
            continue
        cur += ln
    if cur:
        frags.append(cur)
    return frags


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{}\"']", s) or s != s.strip():
        return json.dumps(s, ensure_ascii=False)
    return s


def render_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            if v and isinstance(v[0], dict):
                lines.append(f"{k}:")
                for item in v:
                    inner = ", ".join(f"{ik}: {_yaml_scalar(iv)}" for ik, iv in item.items())
                    lines.append(f"  - {{{inner}}}")
            else:
                lines.append(f"{k}: [{', '.join(_yaml_scalar(x) for x in v)}]")
        else:
            lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def render_page_text(page: dict[str, Any]) -> str:
    title = page.get("title") or page["repo_path"]
    header = f"# [{page['repo_path']}] {title}"
    meta: dict[str, Any] = {"content_kind": page["content_kind"], "repo_path": page["repo_path"]}
    if page.get("symbol"):
        meta["symbol"] = page["symbol"]
    if page.get("language"):
        meta["language"] = page["language"]
    if page.get("module"):
        meta["module"] = page["module"]
    if page.get("summary"):
        meta["summary"] = page["summary"]
    if page.get("symbols"):
        meta["wiki_symbols"] = page["symbols"]
    if page.get("depends_on"):
        meta["wiki_depends_on"] = page["depends_on"]
    if page.get("called_by"):
        meta["wiki_called_by"] = page["called_by"]
    if page.get("files"):
        meta["files"] = page["files"]
    return f"{header}\n{render_frontmatter(meta)}\n\n{page.get('body') or ''}\n"


def page_to_docs(
    page: dict[str, Any], *, repo_url: str, repo_ref: str, chunk_size: int
) -> list[dict[str, Any]]:
    full = render_page_text(page)
    header = f"# [{page['repo_path']}] {page.get('title') or page['repo_path']}"
    frags = chunk_fragments(full, chunk_size)
    n = len(frags)
    # Wiki provenance rides under a nested `metadata` object. The OpenRAG ingest callback
    # (auth_mode=openrag, used by Knowledge-UI uploads) rebuilds each chunk from a fixed
    # allow-list of stock fields and drops everything else top-level — but it passes
    # `metadata` through verbatim, so code-wiki fields land as `metadata.*` in OpenSearch.
    # CodeWikiSearch/Reader/Deps query and read both `metadata.<f>` and top-level `<f>`.
    wiki: dict[str, Any] = {
        "title": page.get("symbol") or page["repo_path"],
        "content_kind": page["content_kind"],
        "wiki_kind": "page",
        "repo_path": page["repo_path"],
        "language": page.get("language", ""),
        "module": page.get("module", ""),
        "wiki_summary": page.get("summary", ""),
        "symbol": page.get("symbol", ""),
        "wiki_symbols": json.dumps(page.get("symbols") or [], ensure_ascii=False),
        "wiki_depends_on": json.dumps(page.get("depends_on") or [], ensure_ascii=False),
        "wiki_called_by": json.dumps(page.get("called_by") or [], ensure_ascii=False),
        "wiki_files": json.dumps(page.get("files") or [], ensure_ascii=False),
        "repo_url": repo_url,
        "repo_ref": repo_ref,
        "num_chunks": n,
    }
    if page.get("line_start"):
        wiki["line_start"] = page["line_start"]
        wiki["line_end"] = page.get("line_end", page["line_start"])
    if page.get("source_excerpt"):
        wiki["wiki_source"] = page[
            "source_excerpt"
        ]  # raw source lines — evidence for read_wiki_page
    # Stock OpenRAG "documents" fields so these pages show up (and are dated /
    # deletable) in the Knowledge UI, which lists files by aggregating on the
    # `filename` keyword and reads these via top_hits. `owner` is intentionally
    # left unset: with document-level security an ownerless doc matches the
    # "owner does not exist" clause and is visible to every user.
    # On the callback path the backend overrides filename/document_id/source_url
    # with the uploaded file's values; on direct writes these are kept as-is.
    # Symbol pages share their file page's repo_path, so the symbol (and its line, for overloads)
    # joins the page identity. Every other page keeps its original id.
    identity = f"{repo_url}@{repo_ref}:{page['repo_path']}"
    if page.get("symbol"):
        identity += f"::{page['symbol']}:{page.get('line_start', '')}"
    base = {
        "filename": page["repo_path"],
        "mimetype": "text/markdown",
        "export_format": "Markdown",
        "document_id": hashlib.sha1(identity.encode()).hexdigest(),
        "connector_type": "code_wiki",
        "source_url": (
            f"{repo_url.rstrip('/')}/blob/{repo_ref or 'HEAD'}/{page['repo_path']}"
            if repo_url and "::" not in page["repo_path"]
            else (repo_url or "")
        ),
        "indexed_time": datetime.now(UTC).isoformat(),
    }
    out: list[dict[str, Any]] = []
    for i, frag in enumerate(frags):
        d = dict(base)
        d["text"] = frag if i == 0 else f"{header}\n\n{frag}"
        d["metadata"] = {
            **wiki,
            "source_url": base["source_url"],
            "wiki_markdown": frag,
            "chunk_index": i,
        }
        out.append(d)
    return out


def _cite(rp: str, s: dict[str, Any]) -> str:
    ls, le = s.get("line_start"), s.get("line_end")
    return f"`{rp}:{ls}-{le}`" if ls and le and le != ls else f"`{rp}:{ls}`"


def deterministic_file_body(
    f: dict[str, Any], symbols: list[dict[str, Any]], edges: dict[str, list[str]]
) -> str:
    rp = f["repo_path"]
    lines = [
        f"## File `{rp}`",
        "",
        f"Language: {f['language'] or 'unknown'}. "
        f"{len(f['text'].splitlines())} lines, {len(symbols)} top-level symbol(s).",
        "",
    ]
    if symbols:
        lines += [
            "## Symbols",
            "",
            *[f"- **{s['symbol']}** ({s['kind']}) — {_cite(rp, s)}" for s in symbols],
            "",
        ]
    if edges.get("depends_on"):
        lines += ["## Depends on", "", *[f"- `{d}`" for d in edges["depends_on"]], ""]
    if edges.get("called_by"):
        lines += ["## Referenced by", "", *[f"- `{c}`" for c in edges["called_by"]], ""]
    return "\n".join(lines)


def deterministic_symbol_body(rp: str, sym: dict[str, Any], source_lines: list[str]) -> str:
    ls, le = sym["line_start"], sym["line_end"]
    excerpt = "\n".join(source_lines[ls - 1 : min(le, ls + 40)])
    return (
        f"## `{sym['symbol']}` ({sym['kind']})\n\nDefined at {_cite(rp, sym)}.\n\n"
        f"```\n{excerpt}\n```\n"
    )


def deterministic_module_body(module: str, files: list[str], readme: str | None) -> str:
    lines = [
        f"## Module `{module or '(repo root)'}`",
        "",
        f"{len(files)} file(s).",
        "",
        "## Files",
        "",
        *[f"- `{p}`" for p in sorted(files)],
        "",
    ]
    if readme:
        lines += ["## Docs", "", f"See `{readme}`.", ""]
    return "\n".join(lines)


def deterministic_overview_body(manifest: dict[str, Any], repo_url: str) -> str:
    mods = sorted(m for m in manifest["modules"] if m)
    total_syms = sum(len(v) for v in manifest["symbols"].values())
    return "\n".join(
        [
            "## Repository overview",
            "",
            f"Source: {repo_url or '(local)'}.",
            f"{len(manifest['tree'])} file(s) across {len(mods)} module(s), "
            f"{total_syms} indexed symbol(s).",
            "",
            "## Modules",
            "",
            *[f"- `{m}` ({len(manifest['modules'][m])} file(s))" for m in mods],
            "",
        ]
    )


def deterministic_doc_body(f: dict[str, Any]) -> str:
    return f"## Doc `{f['repo_path']}`\n\n{_clip(f['text'], 8000)}\n"


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n…(truncated)…"


def _repo_name(repo_url: str) -> str:
    if not repo_url:
        return "repository"
    tail = repo_url.rstrip("/").rsplit("/", 1)[-1] if "/" in repo_url else repo_url
    return re.sub(r"\.git$", "", tail)


def build_pages(
    files: list[dict[str, Any]],
    manifest: dict[str, Any],
    edges: dict[str, dict[str, list[str]]],
    *,
    summarize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    symbol_page_min_lines: int = 50,
    repo_url: str = "",
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []

    def _summ(ctx: dict[str, Any], det_body: str) -> tuple[str, str]:
        if summarize is None:
            return "", det_body
        try:
            r = summarize(ctx) or {}
            return (r.get("summary") or ""), (r.get("body") or det_body)
        except Exception:  # noqa: BLE001
            return "", det_body

    det = deterministic_overview_body(manifest, repo_url)
    summ, body = _summ(
        {
            "kind": "overview",
            "manifest_tree": manifest["tree"],
            "modules": sorted(m for m in manifest["modules"] if m),
        },
        det,
    )
    pages.append(
        {
            "content_kind": "wiki_overview",
            "repo_path": f"repo::{_repo_name(repo_url)}",
            "title": f"{_repo_name(repo_url)} — architecture & index",
            "language": "",
            "module": "",
            "summary": summ,
            "body": body,
            "files": manifest["tree"][:200],
        }
    )

    for module, mfiles in sorted(manifest["modules"].items()):
        if not module:
            continue
        readme = manifest["readmes"].get(module)
        det = deterministic_module_body(module, mfiles, readme)
        summ, body = _summ(
            {"kind": "module", "module": module, "files": sorted(mfiles), "readme": readme}, det
        )
        pages.append(
            {
                "content_kind": "wiki_module_page",
                "repo_path": module,
                "title": f"Module: {posixpath.basename(module) or module}",
                "language": "",
                "module": posixpath.dirname(module),
                "summary": summ,
                "body": body,
                "files": sorted(mfiles),
                "depends_on": sorted(
                    {
                        d
                        for p in mfiles
                        for d in edges.get(p, {}).get("depends_on", [])
                        if module_of(d) != module
                    }
                ),
            }
        )

    for f in files:
        rp = f["repo_path"]
        syms = manifest["symbols"].get(rp, [])
        fedges = edges.get(rp, {"depends_on": [], "called_by": []})
        source_lines = f["text"].split("\n")
        kind = "wiki_doc_page" if f.get("is_doc") else "wiki_file_page"
        det = (
            deterministic_doc_body(f)
            if f.get("is_doc")
            else deterministic_file_body(f, syms, fedges)
        )
        summ, body = _summ(
            {
                "kind": kind,
                "repo_path": rp,
                "language": f["language"],
                "symbols": syms,
                "depends_on": fedges["depends_on"],
                "called_by": fedges["called_by"],
                "source": _clip(f["text"], 12000),
            },
            det,
        )
        pages.append(
            {
                "content_kind": kind,
                "repo_path": rp,
                "title": rp,
                "language": f["language"],
                "module": module_of(rp),
                "summary": summ,
                "body": body,
                "symbols": syms,
                "depends_on": fedges["depends_on"],
                "called_by": fedges["called_by"],
            }
        )

        if not f.get("is_doc") and len(source_lines) >= symbol_page_min_lines:
            for sym in syms:
                det_s = deterministic_symbol_body(rp, sym, source_lines)
                s_summ, s_body = _summ(
                    {
                        "kind": "symbol",
                        "repo_path": rp,
                        "language": f["language"],
                        "symbol": sym,
                        "called_by": fedges["called_by"],
                        "source": "\n".join(source_lines[sym["line_start"] - 1 : sym["line_end"]])[
                            :8000
                        ],
                    },
                    det_s,
                )
                pages.append(
                    {
                        "content_kind": "wiki_symbol_page",
                        "repo_path": rp,
                        "title": sym["symbol"],
                        "symbol": sym["symbol"],
                        "language": f["language"],
                        "module": module_of(rp),
                        "summary": s_summ,
                        "body": s_body,
                        "symbols": [sym],
                        "depends_on": fedges["depends_on"],
                        "called_by": fedges["called_by"],
                        "line_start": sym["line_start"],
                        "line_end": sym["line_end"],
                        "source_excerpt": "\n".join(
                            source_lines[sym["line_start"] - 1 : sym["line_end"]]
                        )[:6000],
                    }
                )
    return pages


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------
class CodeWikiBuilder(Component):
    display_name = "Code Wiki Builder"
    description = (
        "Turn the RepoLoader payload into wiki pages (overview/module/file/symbol/doc) with "
        "LLM summaries and exact-span provenance, then emit OpenSearch docs."
    )
    icon = "BookOpen"
    name = "CodeWikiBuilder"

    inputs = [
        HandleInput(
            name="repo_data",
            display_name="Repo",
            input_types=["Data"],
            info="Payload from RepoLoader (files + manifest + resolved edges).",
        ),
        HandleInput(
            name="model",
            display_name="Language Model",
            input_types=["LanguageModel"],
            info="Any Language Model. Writes each page's summary/body. "
            "Optional — without it, deterministic pages are emitted.",
        ),
        IntInput(
            name="chunk_size",
            display_name="Chunk size (chars)",
            value=3000,
            advanced=True,
            info="Split each page's text into fragments of at most this many characters so each "
            "fits the embedding model's context; the reader reassembles them losslessly.",
        ),
        IntInput(
            name="symbol_page_min_lines",
            display_name="Symbol-page threshold (lines)",
            value=50,
            advanced=True,
            info="Files with >= this many lines also get one wiki_symbol_page per top-level "
            "class/function (fine-grained retrieval). Smaller files stay as one file page. "
            "0 or empty uses the default (50).",
        ),
        IntInput(name="max_tokens", display_name="LLM max tokens", value=1200, advanced=True),
        BoolInput(
            name="use_llm",
            display_name="Use LLM summaries",
            value=True,
            advanced=True,
            info="Off = deterministic pages only (fast, no model calls).",
        ),
    ]

    outputs = [Output(display_name="Docs", name="docs_out", method="build_docs")]

    def _notify(self, msg: str) -> None:
        self.status = msg
        try:
            self.log(msg)
        except Exception:  # noqa: BLE001
            pass

    def _repo_payload(self) -> dict[str, Any]:
        item = self.repo_data
        if isinstance(item, list):
            item = item[0] if item else None
        data = item.data if isinstance(item, Data) else (item or {})
        repo = data.get("repo") if isinstance(data, dict) else None
        if not repo or not repo.get("files"):
            raise RuntimeError(
                "CodeWikiBuilder received no repo payload from RepoLoader "
                "(expected data['repo']['files'])."
            )
        return repo

    def _make_summarizer(self) -> Callable[[dict[str, Any]], dict[str, Any]] | None:
        if not getattr(self, "use_llm", True) or getattr(self, "model", None) is None:
            return None
        max_tokens = int(getattr(self, "max_tokens", 1200) or 1200)
        state = {"calls": 0, "fails": 0}

        def summarize(ctx: dict[str, Any]) -> dict[str, Any]:
            user = (
                "Write the wiki page for the following. Facts (JSON):\n\n"
                f"{json.dumps(ctx, ensure_ascii=False)[:14000]}"
            )
            messages = [("system", _WIKI_SYSTEM), ("human", user)]
            try:
                try:
                    model = self.model.bind(
                        max_tokens=max_tokens, response_format={"type": "json_object"}
                    )
                except Exception:  # noqa: BLE001 - model may not accept these kwargs
                    model = self.model
                resp = model.invoke(messages)
                content = getattr(resp, "content", resp)
                parsed = _extract_json(content if isinstance(content, str) else str(content))
                state["calls"] += 1
                return {
                    "summary": str(parsed.get("summary") or "").strip(),
                    "body": str(parsed.get("body") or "").strip(),
                }
            except Exception:  # noqa: BLE001 - fall back to deterministic body
                state["fails"] += 1
                return {}

        self._summ_state = state
        return summarize

    def build_docs(self) -> list[Data]:
        repo = self._repo_payload()
        files = repo["files"]
        manifest = repo["manifest"]
        edges = repo["edges"]
        repo_url = repo.get("repo_url", "")
        repo_ref = repo.get("repo_ref", "")

        summarize = self._make_summarizer()
        self._notify(
            f"Building wiki for {len(files)} file(s) "
            f"({'LLM summaries' if summarize else 'deterministic'})…"
        )
        pages = build_pages(
            files,
            manifest,
            edges,
            summarize=summarize,
            symbol_page_min_lines=int(getattr(self, "symbol_page_min_lines", 50) or 50),
            repo_url=repo_url,
        )

        chunk_size = int(getattr(self, "chunk_size", 3000) or 3000)
        out: list[Data] = []
        for pg in pages:
            for doc in page_to_docs(
                pg, repo_url=repo_url, repo_ref=repo_ref, chunk_size=chunk_size
            ):
                out.append(Data(data=doc))

        if not out:
            raise RuntimeError("CodeWikiBuilder produced 0 docs.")
        by_kind: dict[str, int] = {}
        for pg in pages:
            by_kind[pg["content_kind"]] = by_kind.get(pg["content_kind"], 0) + 1
        llm_note = ""
        if getattr(self, "_summ_state", None):
            llm_note = f" · LLM ok={self._summ_state['calls']} fail={self._summ_state['fails']}"
        self._notify(f"Built {len(out)} doc(s) from {len(pages)} page(s) {by_kind}{llm_note}")
        return out
