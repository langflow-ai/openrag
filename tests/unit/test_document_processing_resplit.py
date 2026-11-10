"""Tests for resplit_chunks_character_windows."""

from src.utils.document_processing import IMAGE_PLACEHOLDER, resplit_chunks_character_windows


def test_invalid_returns_original():
    chunks = [{"page": 1, "text": "hello world" * 50}]
    assert resplit_chunks_character_windows(chunks, 0, 0) is chunks
    assert resplit_chunks_character_windows(chunks, 10, 10) is chunks
    assert resplit_chunks_character_windows(chunks, 5, 6) is chunks


def test_non_dict_chunk_passthrough():
    chunks = ["not-a-dict", {"page": 1, "text": "x" * 30}]
    out = resplit_chunks_character_windows(chunks, 10, 2)
    assert out[0] == "not-a-dict"
    assert len(out) == 1 + 4  # one long dict chunk -> 4 windows


def test_short_text_unchanged_count():
    chunks = [{"page": 2, "type": "text", "text": "short"}]
    out = resplit_chunks_character_windows(chunks, 100, 20)
    assert len(out) == 1
    assert out[0]["text"] == "short"
    assert out[0]["page"] == 2


def test_image_placeholder_is_not_split():
    chunks = [{"page": 1, "type": "picture", "text": IMAGE_PLACEHOLDER}]

    out = resplit_chunks_character_windows(chunks, 1, 0)

    assert out == chunks


def test_long_text_windows_with_overlap():
    # 22 chars, size 10, overlap 4 -> stride 6; third window reaches end
    text = "abcdefghijklmnopqrstuv"
    assert len(text) == 22
    chunks = [{"page": 1, "text": text}]
    out = resplit_chunks_character_windows(chunks, 10, 4)
    assert len(out) == 3
    assert out[0]["text"] == "abcdefghij"
    assert out[1]["text"] == "ghijklmnop"
    assert out[2]["text"] == "mnopqrstuv"


def test_extract_relevant_with_missing_page_no():
    from src.utils.document_processing import extract_relevant

    # Docling JSON representation where page_no is missing in prov (e.g. for asciidoc/html)
    doc_dict = {
        "origin": {"binary_hash": "hash123", "filename": "test.adoc", "mimetype": "text/asciidoc"},
        "texts": [
            {
                "text": "Hello Asciidoc World!",
                "prov": [],  # empty prov
            },
            {
                "text": "Second paragraph of text.",
                "prov": [{"some_other_key": "val"}],  # prov present but no page_no
            },
        ],
        "tables": [],
    }

    result = extract_relevant(doc_dict)
    assert result["id"] == "hash123"
    assert result["filename"] == "test.adoc"
    assert result["mimetype"] == "text/asciidoc"
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["page"] == 1
    assert "Hello Asciidoc World!" in result["chunks"][0]["text"]
    assert "Second paragraph of text." in result["chunks"][0]["text"]


def test_split_chunks_by_max_tokens_under_limit():
    from src.utils.document_processing import split_chunks_by_max_tokens

    chunks = [
        {"page": 1, "type": "text", "text": "hello world"},
        {"page": 2, "type": "table", "text": "some other text"},
    ]
    out = split_chunks_by_max_tokens(chunks, max_tokens=100)
    assert len(out) == 2
    assert out[0]["text"] == "hello world"
    assert out[1]["text"] == "some other text"


def test_split_chunks_by_max_tokens_exceeding():
    from src.utils.document_processing import split_chunks_by_max_tokens

    # "hello world" is 2 tokens in cl100k_base encoding. If we limit to 1 token per chunk:
    chunks = [{"page": 5, "type": "table", "table_index": 0, "text": "hello world"}]
    # We use cl100k_base (standard for gpt-4/text-embedding-3)
    out = split_chunks_by_max_tokens(chunks, max_tokens=1, model="text-embedding-3-small")
    assert len(out) == 2
    assert out[0]["page"] == 5
    assert out[0]["type"] == "table"
    assert out[0]["table_index"] == 0
    assert out[0]["text"] == "hello"
    assert out[1]["page"] == 5
    assert out[1]["type"] == "table"
    assert out[1]["table_index"] == 0
    assert out[1]["text"] == " world"


def test_extract_relevant_safeguard_none_table_data():
    from src.utils.document_processing import extract_relevant

    doc_dict = {
        "origin": {"binary_hash": "hash456", "filename": "test.csv", "mimetype": "text/csv"},
        "texts": [],
        "tables": [
            {
                "prov": [{"page_no": 1}],
                "data": None,  # Simulate missing table data / structure
            }
        ],
    }
    result = extract_relevant(doc_dict)
    assert result["id"] == "hash456"
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["type"] == "table"
    assert (
        result["chunks"][0]["text"] == ""
    )  # should handle None data and produce empty string or no cells


# 501 cl100k tokens. A 500-token slice of this string decodes to text that
# encodes back to 501, which is the Watsonx cap in the non-Langflow ingest path.
_WATSONX_CAP_OVERFLOW = (
    "地理的には、ユーラシア大陸北西の半島部を包括し、ウラル山脈及びコーカサス山脈の分水嶺とウラル川・"
    "カスピ海・黒海、そして黒海とエーゲ海を繋ぐボスポラス海峡-マルマラ海-ダーダネルス海峡が、アジアと区分される東の境界となる。\n"
    "面積から見るとヨーロッパ州は世界で2番目に小さな大州であり、1018万kmは地球表面積の2%、陸地に限れば6.8%を占める。"
    "アジアに跨る領土を持つロシアは、ヨーロッパ50か国の中で面積および人口第1位の国家である。"
    "対照的に最も小さな国家はバチカン市国である。総人口はアジア・アフリカに次ぐ7億3300万である。これは地球総人口の11%である。\n"
    "ヨーロッパ、特に古代ギリシアは西洋文明発祥の地である。これは、16世紀以降の植民地主義の始まりとともに世界中に拡散し、"
    "支配的な役割を果たした。16世紀から20世紀の間、ヨーロッパの国々はアメリカ州、アフリカ、オセアニア、中東、アジアの大部分を支配下に置いた。"
    "2度の世界大戦はヨーロッパを戦火で覆い、20世紀中頃の西ヨーロ"
)


def test_split_chunks_by_max_tokens_watsonx_window_stays_under_cap():
    import tiktoken

    from src.services.document_service import chunk_texts_for_embeddings
    from src.utils.document_processing import split_chunks_by_max_tokens

    encoding = tiktoken.get_encoding("cl100k_base")
    assert len(encoding.encode(_WATSONX_CAP_OVERFLOW)) == 501

    out = split_chunks_by_max_tokens(
        [{"page": 3, "type": "text", "text": _WATSONX_CAP_OVERFLOW}],
        max_tokens=500,
        model="text-embedding-3-small",
    )
    pieces = [chunk["text"] for chunk in out]
    assert "".join(pieces) == _WATSONX_CAP_OVERFLOW
    assert [len(encoding.encode(piece)) for piece in pieces] == [500, 1]
    assert all(chunk["page"] == 3 for chunk in out)

    batches = chunk_texts_for_embeddings(pieces, max_tokens=500, model="text-embedding-3-small")
    assert [text for batch in batches for text in batch] == pieces


def test_chunk_texts_keeps_one_input_when_text_exceeds_cap():
    from src.services.document_service import chunk_texts_for_embeddings

    batches = chunk_texts_for_embeddings(
        [_WATSONX_CAP_OVERFLOW],
        max_tokens=500,
        model="text-embedding-3-small",
    )
    assert batches == [[_WATSONX_CAP_OVERFLOW]]


def test_split_inside_token_keeps_every_character():
    import tiktoken

    from src.utils.document_processing import _split_text_to_max_tokens

    # The leading space and "ра" share one cl100k token whose next token starts
    # at "б". A one-character fallback must continue inside that token.
    text = " раб"
    encoding = tiktoken.get_encoding("cl100k_base")
    pieces = _split_text_to_max_tokens(text, encoding, 1)
    assert "".join(pieces) == text
    for piece in pieces:
        assert len(encoding.encode(piece)) <= 1 or len(piece) == 1


def test_split_keeps_single_code_point_over_cap():
    from src.utils.document_processing import split_chunks_by_max_tokens

    out = split_chunks_by_max_tokens(
        [{"text": "😀a"}],
        max_tokens=1,
        model="text-embedding-3-small",
    )
    assert [chunk["text"] for chunk in out] == ["😀", "a"]


def test_split_text_to_max_tokens_fuzz():
    import random

    import tiktoken

    from src.utils.document_processing import _split_text_to_max_tokens

    encoding = tiktoken.get_encoding("cl100k_base")
    alphabet = "abc \n地理的には。、😀𠀋👨‍👩‍👧‍👦"
    rng = random.Random(0)
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 200)))
        cap = rng.choice([1, 2, 7, 10, 50, 500])
        pieces = _split_text_to_max_tokens(text, encoding, cap)
        assert "".join(pieces) == text
        assert all(pieces)
        for piece in pieces:
            assert len(encoding.encode(piece)) <= cap or len(piece) == 1


def test_split_chunks_by_max_tokens_emoji_token_override():
    from src.utils.document_processing import split_chunks_by_max_tokens

    # "👨‍👩‍👧‍👦" has len() = 7 in Python, but is 18 tokens in cl100k_base.
    # If max_tokens is 10, then character count (7) < max_tokens (10),
    # but token count (18) > max_tokens (10). It must be split.
    chunks = [{"page": 1, "type": "text", "text": "👨‍👩‍👧‍👦"}]
    out = split_chunks_by_max_tokens(chunks, max_tokens=10, model="text-embedding-3-small")
    # Must be split because 18 > 10.
    assert len(out) > 1
    # Check that chunks reconstruct to the original text
    reconstructed = "".join([c["text"] for c in out])
    assert reconstructed == "👨‍👩‍👧‍👦"
