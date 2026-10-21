#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.25.0,<1",
#     "pypdfium2>=4,<6",
#     "pillow>=10",
#     "reportlab>=4,<5",
# ]
# ///
"""Ingest one fixed document set through both ingest paths and compare them.

Runs against a local dev stack. For each path (OpenRAG's own pipeline, then
Langflow's) it points OpenRAG at a separate index and switches the ingest
mode through ``POST /settings``, uploads the fixtures, and reads back each
file's ``chunk_stats`` and its chunks. Then it restores both settings and
writes a Markdown report.

The script imports no OpenRAG modules, like ``openrag_bulk.py``. The PDF and
image libraries are imported only when the derived fixtures are built.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import statistics
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# ── Fixtures ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fixture:
    """One document in the comparison set.

    ``source`` is a repo-relative path for checked-in documents; derived
    fixtures have none and are built from ``derived_from`` at run time.
    """

    name: str
    kind: str
    source: str | None = None
    derived_from: str | None = None


FIXTURES: tuple[Fixture, ...] = (
    Fixture("ibm_anthropic.pdf", "text-heavy pdf", "openrag-documents/ibm_anthropic.pdf"),
    Fixture("AMCOR_2022.pdf", "table-heavy pdf", "frontend/tests/test-data/AMCOR_2022.pdf"),
    Fixture("docling.pdf", "mixed pdf", "openrag-documents/docling.pdf"),
    Fixture(
        "kubernetes_scanned.pdf",
        "scanned pdf",
        derived_from="frontend/tests/test-data/kubernetes.pdf",
    ),
    Fixture("cat1.pdf", "image-only", "frontend/tests/test-data/cat1.pdf"),
    Fixture("sample.docx", "docx", "frontend/tests/test-data/all_sample_files/sample.docx"),
    Fixture("sample.md", "markdown", "frontend/tests/test-data/all_sample_files/sample.md"),
    Fixture(
        "sampletext.txt", "plain text", "frontend/tests/test-data/all_sample_files/sampletext.txt"
    ),
    Fixture("cjk_sample.pdf", "cjk"),
)


# An original passage written for this script (no third-party text), in
# Chinese and Japanese, so CJK text goes through PDF parsing and chunking.
CJK_PASSAGE: tuple[tuple[str, str, str], ...] = (
    ("STSong-Light", "知识库检索说明", "zh"),
    (
        "STSong-Light",
        "本文档用于测试中文文本的解析与切分。系统首先读取上传的文件，"
        "然后把内容拆分成较小的段落，再为每个段落生成向量并写入索引。"
        "用户提问时，系统会在索引中查找最相关的段落，并把它们交给语言模型来回答问题。"
        "如果切分得太细，段落会失去上下文；如果切分得太粗，检索结果会包含过多无关内容。",
        "zh",
    ),
    (
        "STSong-Light",
        "季度数据：第一季度一百二十件，第二季度一百四十五件，第三季度九十八件。",
        "zh",
    ),
    ("HeiseiMin-W3", "検索の仕組み", "ja"),
    (
        "HeiseiMin-W3",
        "この文書は日本語のテキストの解析と分割を確認するためのものです。"
        "アップロードされたファイルは段落ごとに分けられ、それぞれの段落がベクトルとして索引に保存されます。"
        "質問を受けると、システムは最も関連する段落を探し、言語モデルに渡して回答を作ります。",
        "ja",
    ),
)

SCAN_DPI = 150


def build_scanned_pdf(source: Path, target: Path) -> Path:
    """``source`` rasterised page by page into an image-only PDF (no text layer)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(source))
    pages = [page.render(scale=SCAN_DPI / 72).to_pil().convert("RGB") for page in pdf]
    pages[0].save(target, "PDF", resolution=SCAN_DPI, save_all=True, append_images=pages[1:])
    return target


def build_cjk_pdf(target: Path) -> Path:
    """``CJK_PASSAGE`` as a one-page PDF, with ReportLab's built-in CID fonts."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    story: list[Any] = []
    for font, text, _language in CJK_PASSAGE:
        pdfmetrics.registerFont(UnicodeCIDFont(font))
        heading = len(text) < 20
        style = ParagraphStyle(
            font,
            fontName=font,
            fontSize=16 if heading else 11,
            leading=22 if heading else 17,
            wordWrap="CJK",
        )
        story += [Paragraph(text, style), Spacer(1, 8)]
    SimpleDocTemplate(str(target), pagesize=A4).build(story)
    return target


def materialise_fixtures(repo: Path, workdir: Path) -> list[tuple[Fixture, Path]]:
    """Each fixture's file on disk; derived ones are built into ``workdir``."""
    workdir.mkdir(parents=True, exist_ok=True)
    files = []
    for fixture in FIXTURES:
        if fixture.source is not None:
            path = repo / fixture.source
        elif fixture.derived_from is not None:
            path = build_scanned_pdf(repo / fixture.derived_from, workdir / fixture.name)
        else:
            path = build_cjk_pdf(workdir / fixture.name)
        files.append((fixture, path))
    return files


# ── Comparing chunk text ──────────────────────────────────────────────────

SHINGLE_WORDS = 5
EXAMPLE_CHARS = 200
_TOKEN = re.compile(r"[぀-ヿ㐀-鿿가-힯]|[^\W_]+")


def tokens(text: str) -> list[str]:
    """Lower-cased words, with markup dropped and CJK split into characters."""
    return _TOKEN.findall(text.lower())


def _shingles(words: list[str], size: int) -> set[tuple[str, ...]]:
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


class _Coverage:
    """What text the other path has, read as one stream so its chunk
    boundaries don't hide a passage it does contain."""

    def __init__(self, texts: list[str]):
        self._words = [word for text in texts for word in tokens(text)]
        self._by_size: dict[int, set[tuple[str, ...]]] = {}

    def has(self, shingle: tuple[str, ...]) -> bool:
        size = len(shingle)
        if size not in self._by_size:
            self._by_size[size] = {
                tuple(self._words[i : i + size]) for i in range(len(self._words) - size + 1)
            }
        return shingle in self._by_size[size]


def dropped_content(texts: list[str], other_texts: list[str]) -> dict[str, Any]:
    """How much of ``texts`` the other path's chunks don't contain.

    ``missing_pct`` is the share of the word 5-grams of ``texts`` absent from
    ``other_texts``; ``examples`` are chunks mostly made of missing text.
    """
    other = _Coverage(other_texts)
    total = missing = 0
    examples = []
    for text in texts:
        shingles = _shingles(tokens(text), SHINGLE_WORDS)
        absent = sum(1 for shingle in shingles if not other.has(shingle))
        total += len(shingles)
        missing += absent
        if shingles and absent / len(shingles) > 0.5:
            examples.append(text.strip()[:EXAMPLE_CHARS])
    return {
        "missing_pct": round(100 * missing / total, 1) if total else 0.0,
        "examples": examples,
    }


# ── Samples ───────────────────────────────────────────────────────────────


def is_table_like(text: str) -> bool:
    """Most lines are table rows (``|`` or tab separated).

    The index records no chunk type, so tables are recognised by shape.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    rows = sum(1 for line in lines if line.count("|") >= 2 or "\t" in line)
    return rows / len(lines) > 0.5


def pick_samples(chunks: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """The first chunk, the first table-like chunk and the longest chunk."""
    if not chunks:
        return {"first": None, "table": None, "longest": None}
    return {
        "first": chunks[0],
        "table": next((c for c in chunks if is_table_like(c.get("text") or "")), None),
        "longest": max(chunks, key=lambda c: len(c.get("text") or "")),
    }


# ── Talking to the stack ──────────────────────────────────────────────────


@dataclass(frozen=True)
class IngestPath:
    name: str
    disable_ingest_with_langflow: bool
    index_name: str


# Index names must match ``*documents*`` (the OpenSearch security role).
PATHS: tuple[IngestPath, ...] = (
    IngestPath("openrag", True, "compare-openrag-documents"),
    IngestPath("langflow", False, "compare-langflow-documents"),
)
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class ApiError(RuntimeError):
    """A request to the backend or OpenSearch failed."""


def _checked(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        raise ApiError(
            f"{response.request.method} {response.request.url.path} -> "
            f"{response.status_code}: {response.text[:300]}"
        )
    return response.json()


class OpenRAG:
    """The backend endpoints the comparison uses (local no-auth mode)."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def knowledge_settings(self) -> dict[str, Any]:
        return _checked(self._client.get("/settings"))["knowledge"]

    def update_settings(self, **body: Any) -> None:
        _checked(self._client.post("/settings", json=body))

    def upload(self, files: list[Path]) -> str:
        with ExitStack() as stack:
            parts = [
                (
                    "file",
                    (
                        path.name,
                        stack.enter_context(path.open("rb")),
                        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    ),
                )
                for path in files
            ]
            response = self._client.post(
                "/router/upload_ingest",
                files=parts,
                data={"replace_duplicates": "true"},
            )
        return _checked(response)["task_id"]

    def wait(self, task_id: str, *, poll_seconds: float, timeout_seconds: float) -> dict:
        deadline = time.monotonic() + timeout_seconds
        while True:
            task = _checked(self._client.get(f"/tasks/{task_id}"))
            if task.get("status") in TERMINAL_STATUSES:
                return task
            if time.monotonic() > deadline:
                raise ApiError(
                    f"task {task_id} still {task.get('status')} after {timeout_seconds}s"
                )
            time.sleep(poll_seconds)


class Index:
    """Direct OpenSearch reads: chunk text isn't exposed by the backend."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def delete(self, index: str) -> None:
        response = self._client.delete(f"/{index}")
        if response.status_code != 404:
            _checked(response)

    def chunks(self, index: str, filename: str) -> list[dict[str, Any]]:
        body = {
            "size": 10_000,
            "query": {"term": {"filename": filename}},
            "sort": [{"page": {"order": "asc", "unmapped_type": "integer"}}],
            "_source": ["text", "page"],
        }
        hits = _checked(self._client.post(f"/{index}/_search", json=body))["hits"]["hits"]
        return [hit.get("_source") or {} for hit in hits]


def _ingest(
    api: OpenRAG,
    index: Index,
    path: IngestPath,
    files: list[tuple[Fixture, Path]],
    *,
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, dict[str, Any]]:
    index.delete(path.index_name)
    api.update_settings(
        index_name=path.index_name,
        disable_ingest_with_langflow=path.disable_ingest_with_langflow,
    )
    task_id = api.upload([file for _, file in files])
    task = api.wait(task_id, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds)
    by_name = {f.get("filename"): f for f in (task.get("files") or {}).values()}
    outcome = {}
    for fixture, file in files:
        file_task = by_name.get(file.name) or {}
        result = file_task.get("result") or {}
        outcome[fixture.name] = {
            "status": file_task.get("status", "missing"),
            "error": file_task.get("error"),
            "chunk_stats": result.get("chunk_stats"),
            "chunks": index.chunks(path.index_name, file.name),
        }
    return outcome


def run_comparison(
    api: OpenRAG,
    index: Index,
    files: list[tuple[Fixture, Path]],
    *,
    poll_seconds: float = 3,
    timeout_seconds: float = 1800,
    delete_indexes: bool = False,
) -> dict[str, Any]:
    """Ingest ``files`` through each path; the stack's settings are restored after."""
    settings = api.knowledge_settings()
    original = {
        "index_name": settings.get("index_name"),
        "disable_ingest_with_langflow": settings.get("disable_ingest_with_langflow"),
    }
    by_path: dict[str, dict[str, dict[str, Any]]] = {}
    try:
        for path in PATHS:
            by_path[path.name] = _ingest(
                api,
                index,
                path,
                files,
                poll_seconds=poll_seconds,
                timeout_seconds=timeout_seconds,
            )
    finally:
        api.update_settings(**original)
        if delete_indexes:
            for path in PATHS:
                index.delete(path.index_name)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": settings,
        "documents": [
            {
                "name": fixture.name,
                "kind": fixture.kind,
                "paths": {name: outcome[fixture.name] for name, outcome in by_path.items()},
            }
            for fixture, _ in files
        ],
    }


# ── Report ────────────────────────────────────────────────────────────────

SAMPLE_CHARS = 400
_STAT_ROWS = (
    ("chunk_count", ("chunk_count",)),
    ("chars median", ("chars", "median")),
    ("chars p90", ("chars", "p90")),
    ("chars max", ("chars", "max")),
    ("tokens median", ("tokens", "median")),
    ("tokens p90", ("tokens", "p90")),
    ("tokens max", ("tokens", "max")),
    ("pages", ("pages", "count")),
    ("chunks/page median", ("pages", "chunks_per_page", "median")),
    ("empty_chunks", ("empty_chunks",)),
    ("placeholder_chunks", ("placeholder_chunks",)),
    ("parser", ("parser",)),
    ("chunk_size", ("chunk_size",)),
    ("chunk_overlap", ("chunk_overlap",)),
    ("embedding_model", ("embedding_model",)),
)


def _dig(stats: dict[str, Any] | None, keys: tuple[str, ...]) -> Any:
    value: Any = stats
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _cell(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        value = f"{value:g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _quote(text: str) -> str:
    text = text.strip()
    if len(text) > SAMPLE_CHARS:
        text = text[:SAMPLE_CHARS] + " …"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines()) or "> (empty)"


def compare_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Dropped content both ways and samples per path for one document."""
    names = [path.name for path in PATHS]
    texts = {n: [c.get("text") or "" for c in doc["paths"][n]["chunks"]] for n in names}
    a, b = names
    return {
        "missing": {
            b: dropped_content(texts[a], texts[b]),
            a: dropped_content(texts[b], texts[a]),
        },
        "samples": {n: pick_samples(doc["paths"][n]["chunks"]) for n in names},
    }


def render_report(results: dict[str, Any]) -> str:
    names = [path.name for path in PATHS]
    a, b = names
    settings = results.get("settings") or {}
    lines = [
        "# Ingest path comparison",
        "",
        f"Generated {results.get('generated_at', '')}. Indexes: "
        + ", ".join(f"`{p.index_name}` ({p.name})" for p in PATHS)
        + ".",
        "",
        "Knowledge settings during the run: "
        + ", ".join(
            f"{key}={settings.get(key)}"
            for key in (
                "embedding_provider",
                "embedding_model",
                "chunk_size",
                "chunk_overlap",
                "ocr",
                "picture_descriptions",
                "table_structure",
            )
            if key in settings
        )
        + ".",
        "",
        "Missing text is the share of one path's word 5-grams absent from the other "
        "path's chunks (whitespace and markup ignored).",
        "",
        "## Summary",
        "",
        f"| document | kind | {a} chunks | {b} chunks | missing from {b} | missing from {a} |",
        "|---|---|---|---|---|---|",
    ]
    compared = [(doc, compare_document(doc)) for doc in results["documents"]]
    for doc, comparison in compared:
        counts = [
            _cell(_dig(doc["paths"][n]["chunk_stats"], ("chunk_count",)))
            if doc["paths"][n]["status"] == "completed"
            else doc["paths"][n]["status"]
            for n in names
        ]
        lines.append(
            f"| {doc['name']} | {doc['kind']} | {counts[0]} | {counts[1]} | "
            f"{comparison['missing'][b]['missing_pct']}% | "
            f"{comparison['missing'][a]['missing_pct']}% |"
        )
    lines.append("")
    for name in names:
        per_document = [
            len(doc["paths"][name]["chunks"]) for doc, _ in compared if doc["paths"][name]["chunks"]
        ]
        if per_document:
            lines.append(
                f"- **{name}**: {sum(per_document)} chunks over {len(per_document)} documents, "
                f"median {statistics.median(per_document):g} per document."
            )
    worst = max(
        compared,
        key=lambda item: max(m["missing_pct"] for m in item[1]["missing"].values()),
        default=None,
    )
    if worst is not None:
        doc, comparison = worst
        side, missing = max(comparison["missing"].items(), key=lambda kv: kv[1]["missing_pct"])
        lines.append(
            f"- Largest loss: **{doc['name']}**, {missing['missing_pct']}% of the "
            f"other path's text missing from {side}."
        )
    lines.append("")

    for doc, comparison in compared:
        lines += [f"## {doc['name']}", "", f"Kind: {doc['kind']}.", ""]
        for name in names:
            outcome = doc["paths"][name]
            if outcome["status"] != "completed" or outcome.get("error"):
                lines.append(f"- {name}: {outcome['status']} — {outcome.get('error') or ''}")
        lines += [f"| stat | {a} | {b} |", "|---|---|---|"]
        for label, keys in _STAT_ROWS:
            values = [_cell(_dig(doc["paths"][n]["chunk_stats"], keys)) for n in names]
            lines.append(f"| {label} | {values[0]} | {values[1]} |")
        lines.append("")
        for side in (b, a):
            other = a if side == b else b
            missing = comparison["missing"][side]
            lines.append(f"**Missing from {side}** ({missing['missing_pct']}% of {other}'s text):")
            lines.append("")
            if not missing["examples"]:
                lines += ["Nothing notable.", ""]
            for example in missing["examples"][:3]:
                lines += [_quote(example), ""]
        for name in names:
            lines += [f"### Samples: {name}", ""]
            for label, chunk in comparison["samples"][name].items():
                if chunk is None:
                    lines += [f"*{label}*: none", ""]
                    continue
                lines += [
                    f"*{label}* (page {chunk.get('page')}, {len(chunk.get('text') or '')} chars):",
                    "",
                    _quote(chunk.get("text") or ""),
                    "",
                ]
    return "\n".join(lines).rstrip() + "\n"


# ── Command line ──────────────────────────────────────────────────────────


def _dotenv(repo: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = repo / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return values


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[1]
    env = {**_dotenv(repo), **os.environ}
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--backend-url", default=env.get("OPENRAG_BACKEND_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--opensearch-url",
        default=env.get("OPENSEARCH_URL")
        or f"https://localhost:{env.get('OPENSEARCH_PORT', '9200')}",
    )
    parser.add_argument("--out", type=Path, default=None, help="Report directory")
    parser.add_argument("--only", nargs="*", help="Fixture names to include")
    parser.add_argument("--timeout", type=float, default=1800, help="Seconds per path")
    parser.add_argument(
        "--delete-indexes",
        action="store_true",
        help="Delete both comparison indexes afterwards (kept by default for retrieval eval)",
    )
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = (args.out or Path("~/.openrag/ingest-compare") / stamp).expanduser()
    files = materialise_fixtures(repo, out / "fixtures")
    if args.only:
        files = [(f, p) for f, p in files if f.name in set(args.only)]

    auth = (env.get("OPENSEARCH_USERNAME", "admin"), env.get("OPENSEARCH_PASSWORD", ""))
    with (
        httpx.Client(base_url=args.backend_url, timeout=300) as backend,
        httpx.Client(base_url=args.opensearch_url, auth=auth, verify=False, timeout=60) as search,
    ):
        results = run_comparison(
            OpenRAG(backend),
            Index(search),
            files,
            timeout_seconds=args.timeout,
            delete_indexes=args.delete_indexes,
        )

    (out / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    report = out / "report.md"
    report.write_text(render_report(results), encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
