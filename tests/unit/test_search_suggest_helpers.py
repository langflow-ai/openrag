"""Unit tests for services/search_suggest.py (pure helpers)."""

from services.search_suggest import (
    PREVIEW_KEYWORD,
    PREVIEW_MAX_CHARS,
    PREVIEW_SEMANTIC,
    best_sentence,
    build_preview,
    escape_wildcard,
    extract_candidates,
    normalize_suggest_query,
    preview_from_highlight,
    strip_marks,
)


class TestNormalizeSuggestQuery:
    def test_collapses_whitespace(self):
        assert normalize_suggest_query("  docling   serve ") == "docling serve"

    def test_rejects_short_wildcard_and_non_strings(self):
        assert normalize_suggest_query("a") == ""
        assert normalize_suggest_query("*") == ""
        assert normalize_suggest_query(None) == ""
        assert normalize_suggest_query(123) == ""  # type: ignore[arg-type]

    def test_caps_length(self):
        assert len(normalize_suggest_query("x" * 500)) == 100


def test_escape_wildcard_neutralizes_metacharacters():
    assert escape_wildcard("a*b?c\\d") == "a\\*b\\?c\\\\d"


class TestPreviewFromHighlight:
    def test_adds_ellipsis_when_fragment_is_mid_chunk(self):
        text = "Intro text. The docling library parses PDFs. More text follows here."
        fragment = "The <mark>docling</mark> library parses PDFs"
        line = preview_from_highlight(text, fragment)
        assert line.startswith("…")
        assert line.endswith("…")
        assert "<mark>docling</mark>" in line

    def test_no_ellipsis_when_fragment_is_the_whole_chunk(self):
        text = "docling parses PDFs"
        assert preview_from_highlight(text, "<mark>docling</mark> parses PDFs") == (
            "<mark>docling</mark> parses PDFs"
        )

    def test_long_fragment_is_trimmed_but_keeps_the_match_and_balanced_marks(self):
        text = "x " * 400 + "needle " + "y " * 400
        fragment = "x " * 100 + "<mark>needle</mark> " + "y " * 100
        line = preview_from_highlight(text, fragment)
        assert "<mark>needle</mark>" in line
        assert len(strip_marks(line)) <= PREVIEW_MAX_CHARS + 4
        assert line.count("<mark>") == line.count("</mark>")


class TestBestSentence:
    def test_picks_sentence_with_most_query_words(self):
        text = (
            "The weather was pleasant all week long. "
            "Vector search ranks passages by embedding similarity. "
            "Lunch was served at noon every single day."
        )
        assert best_sentence(text, "embedding similarity") == (
            "Vector search ranks passages by embedding similarity."
        )

    def test_falls_back_to_first_sentence_without_overlap(self):
        text = "First sentence is right here. Second sentence follows it."
        assert best_sentence(text, "zzz") == "First sentence is right here."

    def test_empty_text(self):
        assert best_sentence("   ", "x") is None


class TestBuildPreview:
    def test_prefers_keyword_highlight(self):
        preview = build_preview("t", ["a <mark>b</mark> c"], "b", allow_semantic=True)
        assert preview is not None
        assert preview["kind"] == PREVIEW_KEYWORD

    def test_semantic_fallback_only_when_allowed(self):
        text = "Retrieval augments generation with fetched context passages."
        assert build_preview(text, [], "retrieval", allow_semantic=False) is None
        preview = build_preview(text, [], "retrieval", allow_semantic=True)
        assert preview is not None
        assert preview["kind"] == PREVIEW_SEMANTIC

    def test_nothing_to_show(self):
        assert build_preview(None, [], "x", allow_semantic=True) is None


class TestExtractCandidates:
    def test_completes_partial_word_and_adds_next_word(self):
        texts = [
            "Run docling serve to start the API.",
            "docling serve exposes REST endpoints",
            "The docling project converts documents.",
        ]
        candidates = extract_candidates(texts, "docl")
        assert "docling" in candidates
        assert "docling serve" in candidates
        assert candidates.index("docling") < candidates.index("docling serve")

    def test_skips_stopwords_as_second_word(self):
        assert extract_candidates(["docling and friends"], "docling") == ["docling"]

    def test_multi_word_query_is_matched_across_whitespace(self):
        candidates = extract_candidates(["docling   serve   works"], "docling serve")
        assert candidates[0] == "docling serve"

    def test_regex_metacharacters_in_query_are_literal(self):
        assert extract_candidates(["a (b) c"], "(b") == ["(b"]
        assert extract_candidates(["anything"], "[") == []

    def test_ignores_non_string_texts_and_empty_query(self):
        assert extract_candidates([None, 3], "docling") == []  # type: ignore[list-item]
        assert extract_candidates(["docling"], "  ") == []
