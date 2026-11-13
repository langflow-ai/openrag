"""Dataset loading and validation for the OpenRAG retrieval evaluation harness.

The dataset is a directory of corpus files plus a JSONL file of labeled
questions. Everything is validated before the harness touches a live stack, so
a typo in a label fails fast instead of silently scoring as a miss.

Standard library only, so it can be unit-tested without the SDK or a stack.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

REQUIRED_FIELDS = frozenset({"query", "expected_files"})
OPTIONAL_FIELDS = frozenset({"id", "expected_text", "expected_answer", "tags"})


class DatasetError(ValueError):
    """The corpus or the question file is invalid. The message lists every problem."""


@dataclass(frozen=True)
class Query:
    id: str
    query: str
    expected_files: tuple[str, ...]
    expected_text: str | None = None
    tags: tuple[str, ...] = ()
    expected_answer: str | None = None


def list_corpus(corpus_dir: Path) -> list[str]:
    """Sorted filenames of the corpus documents (top level, hidden files skipped)."""
    if not corpus_dir.is_dir():
        raise DatasetError(f"corpus directory not found: {corpus_dir}")
    names = sorted(
        path.name
        for path in corpus_dir.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
    if not names:
        raise DatasetError(f"corpus directory is empty: {corpus_dir}")
    return names


def _is_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _parse_row(row: object, corpus_names: frozenset[str]) -> tuple[Query | None, list[str]]:
    if not isinstance(row, dict):
        return None, ["row must be a JSON object"]

    problems: list[str] = []
    unknown = sorted(set(row) - REQUIRED_FIELDS - OPTIONAL_FIELDS)
    if unknown:
        problems.append(f"unknown field(s): {', '.join(unknown)}")

    query = row.get("query")
    if not isinstance(query, str) or not query.strip():
        problems.append("'query' must be a non-empty string")

    expected_files = row.get("expected_files")
    if not _is_string_list(expected_files):
        problems.append("'expected_files' must be a non-empty list of filenames")
    else:
        assert isinstance(expected_files, list)
        if len(set(expected_files)) != len(expected_files):
            problems.append("'expected_files' lists the same file twice")
        for name in expected_files:
            if name not in corpus_names:
                problems.append(f"expected file not in corpus: {name}")

    query_id = row.get("id", query)
    if "id" in row and (not isinstance(query_id, str) or not query_id.strip()):
        problems.append("'id' must be a non-empty string")

    expected_text = row.get("expected_text")
    if expected_text is not None and (
        not isinstance(expected_text, str) or not expected_text.strip()
    ):
        problems.append("'expected_text' must be a non-empty string")

    expected_answer = row.get("expected_answer")
    if "expected_answer" in row and (
        not isinstance(expected_answer, str) or not expected_answer.strip()
    ):
        problems.append("'expected_answer' must be a non-empty string")

    tags = row.get("tags", [])
    if tags != [] and not _is_string_list(tags):
        problems.append("'tags' must be a list of non-empty strings")

    if problems:
        return None, problems
    return (
        Query(
            id=query_id.strip(),
            query=query.strip(),
            expected_files=tuple(expected_files),
            expected_text=expected_text,
            tags=tuple(tags),
            expected_answer=expected_answer,
        ),
        [],
    )


def _normalize(text: str) -> str:
    # Same comparison the scorer uses: case-folded and single-spaced.
    return " ".join(text.casefold().split())


def _snippet_problems(query: Query, corpus_dir: Path, cache: dict[str, str]) -> list[str]:
    """Expected files that do not contain the question's ``expected_text``.

    A snippet that is not in the source document can never be found in one of
    its chunks, so the question would score zero on every run.
    """
    if query.expected_text is None:
        return []
    needle = _normalize(query.expected_text)
    problems = []
    for name in query.expected_files:
        if name not in cache:
            cache[name] = _normalize((corpus_dir / name).read_text(encoding="utf-8"))
        if needle not in cache[name]:
            problems.append(f"'expected_text' {query.expected_text!r} does not appear in {name}")
    return problems


def load_queries(
    path: Path,
    corpus_names: list[str],
    corpus_dir: Path | None = None,
) -> list[Query]:
    """Load and validate the question file.

    Raises DatasetError naming the line of every malformed row, so one run of
    the validator surfaces all problems. With ``corpus_dir``, also checks that
    each ``expected_text`` appears in every file the question expects.
    """
    if not path.is_file():
        raise DatasetError(f"question file not found: {path}")

    known = frozenset(corpus_names)
    queries: list[Query] = []
    errors: list[str] = []
    first_seen: dict[str, int] = {}
    corpus_text: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{line_number}: invalid JSON ({exc.msg})")
            continue
        query, problems = _parse_row(row, known)
        errors.extend(f"{path.name}:{line_number}: {problem}" for problem in problems)
        if query is None:
            continue
        if query.id in first_seen:
            errors.append(
                f"{path.name}:{line_number}: duplicate id {query.id!r} "
                f"(first used on line {first_seen[query.id]})"
            )
            continue
        first_seen[query.id] = line_number
        queries.append(query)
        if corpus_dir is not None:
            errors.extend(
                f"{path.name}:{line_number}: {problem}"
                for problem in _snippet_problems(query, corpus_dir, corpus_text)
            )

    if not queries and not errors:
        errors.append(f"{path.name}: no questions found")
    if errors:
        raise DatasetError("\n".join(errors))
    return queries


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_corpus(corpus_dir: Path, corpus_names: list[str]) -> str:
    """One digest over every corpus filename and its content, in sorted order."""
    digest = hashlib.sha256()
    for name in sorted(corpus_names):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hash_file(corpus_dir / name).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


# Every run uploads its documents as ``eval-<8 hex digits>-<corpus filename>``.
RUN_ID_PATTERN = re.compile(r"^(eval-[0-9a-f]{8})-(.+)$")


@dataclass(frozen=True)
class Leftover:
    """A document an earlier run uploaded and did not delete."""

    filename: str
    run_id: str
    indexed_time: datetime | None  # None when the stack's timestamp could not be read


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def find_leftovers(
    files: Iterable[tuple[str, str | None]], corpus_names: Collection[str]
) -> list[Leftover]:
    """Pick the eval uploads out of ``(filename, indexed_time)`` pairs from the stack.

    A file counts only when its name is a run prefix followed by a corpus
    filename, so a user document that merely starts with ``eval-`` is never
    matched.
    """
    leftovers = []
    for filename, indexed_time in files:
        match = RUN_ID_PATTERN.match(filename)
        if match and match.group(2) in corpus_names:
            leftovers.append(Leftover(filename, match.group(1), _parse_time(indexed_time)))
    return sorted(leftovers, key=lambda item: (item.run_id, item.filename))


def old_enough(leftover: Leftover, now: datetime, min_age: timedelta) -> bool:
    """Whether a leftover is old enough to delete safely.

    A recent upload may belong to a run that is still going, possibly someone
    else's on a shared stack, and a file without a readable timestamp cannot be
    shown to be old, so both are kept.
    """
    return leftover.indexed_time is not None and now - leftover.indexed_time >= min_age


def retrieval_queries_hash(path: Path) -> str:
    """Hash the legacy question file without additive answer references.

    Rows with no answer reference keep their exact bytes. Answer-labeled rows
    use the existing JSONL formatting, so the tracked phase-1 baseline remains
    comparable. The full file hash is recorded separately for provenance.
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.strip():
            row = json.loads(line)
            if "expected_answer" in row:
                del row["expected_answer"]
                line = json.dumps(row, ensure_ascii=False) + ("\n" if line.endswith("\n") else "")
        lines.append(line)
    return hashlib.sha256("".join(lines).encode()).hexdigest()
