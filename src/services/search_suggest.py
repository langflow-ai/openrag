"""Pure helpers for the search-suggestion endpoint.

Everything here is side-effect free so it can be unit-tested without
OpenSearch: building the one-line "why did this file match" preview, and
deriving query-completion candidates from the text of top-ranked chunks.
"""

import re
from collections import Counter

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
PREVIEW_MAX_CHARS = 180

PREVIEW_KEYWORD = "keyword"
PREVIEW_SEMANTIC = "semantic"

_MARK_BLOCK = re.compile(r"<mark>.*?</mark>", re.DOTALL)
_MARK_TAG = re.compile(r"</?mark>")
_PARTIAL_TAG_AT_END = re.compile(r"<[^>]{0,6}$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_TOKEN = re.compile(r"\w+", re.UNICODE)

# Words that make a poor second word in a "query + next word" completion.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
        "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "with",
    }
)  # fmt: skip


def normalize_suggest_query(query: str | None) -> str:
    """Trim, collapse whitespace and cap length. Returns "" for unusable input."""
    if not isinstance(query, str):
        return ""
    cleaned = " ".join(query.split())[:MAX_QUERY_LENGTH]
    if len(cleaned) < MIN_QUERY_LENGTH or cleaned == "*":
        return ""
    return cleaned


def strip_marks(fragment: str) -> str:
    return _MARK_TAG.sub("", fragment)


def escape_wildcard(value: str) -> str:
    """Escape OpenSearch wildcard metacharacters so user input is matched literally."""
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")


def _truncate_plain(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut or text[:max_chars]}…"


def _trim_fragment(fragment: str, max_chars: int) -> str:
    """Shrink an over-long highlight fragment around its first <mark>."""
    if len(strip_marks(fragment)) <= max_chars:
        return fragment

    match = _MARK_BLOCK.search(fragment)
    if not match:
        return _truncate_plain(fragment, max_chars)

    before, mark, after = fragment[: match.start()], match.group(0), fragment[match.end() :]
    budget = max(max_chars - len(strip_marks(mark)), 0)
    keep_before = budget // 3
    keep_after = budget - min(keep_before, len(before))

    if len(before) > keep_before:
        # Drop the (probably cut) leading word fragment.
        before = "…" + before[-keep_before:].split(" ", 1)[-1] if keep_before else "…"
    if len(strip_marks(after)) > keep_after:
        after = after[:keep_after]
        # Never leave a half-open <mark> or a partial tag behind.
        after = _PARTIAL_TAG_AT_END.sub("", after)
        if after.rfind("<mark>") > after.rfind("</mark>"):
            after = after[: after.rfind("<mark>")]
        after = after.rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return before + mark + after


def preview_from_highlight(text: str | None, fragment: str) -> str:
    """Turn an OpenSearch ``<mark>`` fragment into a one-line preview.

    ``…`` marks the side(s) where the fragment was cut out of the chunk, so the
    reader can tell the line is an excerpt.
    """
    plain = strip_marks(fragment)
    start = text.find(plain) if text else -1
    line = _trim_fragment(" ".join(fragment.split()), PREVIEW_MAX_CHARS)
    if start > 0 and not line.startswith("…"):
        line = f"…{line}"
    if start >= 0 and text and start + len(plain) < len(text) and not line.endswith("…"):
        line = f"{line}…"
    return line


def best_sentence(text: str, query: str) -> str | None:
    """Pick the sentence sharing the most words with the query (first on ties)."""
    cleaned = text.strip() if isinstance(text, str) else ""
    if not cleaned:
        return None

    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(cleaned) if len(s.strip()) >= 20]
    if not sentences:
        sentences = [cleaned]

    query_tokens = {t.lower() for t in _TOKEN.findall(query)}

    def overlap(sentence: str) -> int:
        return len(query_tokens & {t.lower() for t in _TOKEN.findall(sentence)})

    best = max(sentences, key=overlap)  # max() keeps the first of equal scores
    return _truncate_plain(" ".join(best.split()), PREVIEW_MAX_CHARS)


def build_preview(
    text: str | None, highlights: list[str] | None, query: str, *, allow_semantic: bool
) -> dict[str, str] | None:
    """Return ``{"text", "kind"}`` describing how a chunk relates to the query.

    ``kind`` is ``keyword`` when the line contains ``<mark>``-wrapped matches and
    ``semantic`` for a plain best-matching sentence. Returns None when there is
    nothing meaningful to show.
    """
    if highlights:
        fragment = next((h for h in highlights if isinstance(h, str) and h.strip()), None)
        if fragment:
            return {"text": preview_from_highlight(text, fragment), "kind": PREVIEW_KEYWORD}
    if allow_semantic and text:
        sentence = best_sentence(text, query)
        if sentence:
            return {"text": sentence, "kind": PREVIEW_SEMANTIC}
    return None


def extract_candidates(texts: list[str], query: str, limit: int = 6) -> list[str]:
    """Derive completion candidates (``query`` + rest of word [+ next word]).

    For ``docl`` this yields ``docling`` and ``docling serve`` when the sampled
    chunks contain them. Candidates are ranked by how often they occur.
    """
    normalized = " ".join(query.lower().split())
    if not normalized:
        return []

    body = re.escape(normalized).replace(r"\ ", r"\s+")
    pattern = re.compile(rf"(?<![\w-]){body}([\w-]*)(?:\s+([\w-]+))?", re.IGNORECASE)

    counts: Counter[str] = Counter()
    for text in texts:
        if not isinstance(text, str):
            continue
        for match in pattern.finditer(text):
            completion = normalized + match.group(1).lower()
            counts[completion] += 1
            following = (match.group(2) or "").lower()
            if len(following) >= 2 and following not in _STOPWORDS:
                counts[f"{completion} {following}"] += 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
    return [candidate for candidate, _ in ranked[:limit]]
