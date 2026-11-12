import pytest

from services.search_service import _is_noise_query, _is_noise_token


@pytest.mark.parametrize(
    "query",
    [
        "dddd",
        "xx",
        "dnfjdisfhds",
        "asdkfjhasd",
        "fdjsdifnsji",
        "asdfghjkl",
        "zxcvbnm",
        "qwertyuiop",
        "dddd xx",
    ],
)
def test_gibberish_is_noise(query):
    assert _is_noise_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "dog",
        "log",
        "strengths",
        "https",
        "pgsql",
        "xhtml",
        "rhythms",
        "twelfths",
        "blorfwump",
        "zorbnaxle",
        "parsing tools",
        "tiredness remedy",
        "KV-4471-B",
        "v3.2.9",
        "Straßenbahn",
        "港",
        "dnfjdisfhds parsing",
        "*",
        "",
    ],
)
def test_real_or_mixed_queries_are_not_noise(query):
    assert not _is_noise_query(query)


def test_non_ascii_and_digits_are_never_noise():
    assert not _is_noise_token("港港港港")
    assert not _is_noise_token("12345678")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("and", "and"),
        ("the", "the"),
        ("the of and", "the of and"),
        ("the doctor and the cat", "doctor cat"),
        ("tiredness for", "tiredness"),
        ("for tiredness remedy", "tiredness remedy"),
        ("puppy for the", "puppy"),
        ("The Cat.", "Cat."),
        ("cat", "cat"),
    ],
)
def test_keyword_query_drops_fillers_unless_query_is_all_fillers(query, expected):
    from services.search_service import _keyword_query

    assert _keyword_query(query) == expected


@pytest.mark.parametrize(
    "text",
    [
        "|---------------------------------------|-----------------------|",
        "-----",
        "| | | |",
        "12345 6789",
        "",
        "   ",
        "a b c",
        "✅ 📌",
    ],
)
def test_chunks_without_readable_words_are_dropped(text):
    from services.search_service import _has_readable_text

    assert not _has_readable_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "The Tessalune Free Harbor Authority recorded 4,812 container movements.",
        "港の報告。テッサルーン港では",
        "Отчёт порта.",
        "تقرير الميناء",
        "항만 보고서",
        "| Name | Age |\n|---|---|\n| Ann | 30 |",
        "ok",
        None,
    ],
)
def test_chunks_with_readable_words_are_kept(text):
    from services.search_service import _has_readable_text

    assert _has_readable_text(text)
