"""Tests for Kangxi Radical -> CJK Unified Ideograph normalization.

Some PDF fonts map common kanji glyphs (日, 月, 木, 金, 土) to the visually
identical Kangxi Radical code points (U+2F00..U+2FDF) in their /ToUnicode
CMap. Docling copies those code points through unchanged, so search and the
LLM see different characters from the ones a user types.
"""

from src.utils.document_processing import extract_relevant, normalize_cjk_radicals

KANGXI_ROW = "11 ⽉ 27 ⽇ ( ⽊ )"  # 11 ⽉ 27 ⽇ ( ⽊ )


def test_kangxi_radicals_become_unified_ideographs():
    assert normalize_cjk_radicals(KANGXI_ROW) == "11 月 27 日 ( 木 )"
    assert normalize_cjk_radicals("⾦⼟") == "金土"


def test_every_kangxi_radical_is_mapped():
    radicals = "".join(chr(c) for c in range(0x2F00, 0x2FD6))
    assert not any(0x2F00 <= ord(c) <= 0x2FDF for c in normalize_cjk_radicals(radicals))


def test_other_compatibility_characters_are_left_alone():
    # Full NFKC would rewrite these; the targeted table must not.
    text = "港区虎ノ門２丁目６-１ ㈱ ① ｶﾀｶﾅ （保管中）"
    assert normalize_cjk_radicals(text) == text


def test_extract_relevant_normalizes_text_and_table_chunks():
    doc = {
        "origin": {"filename": "slip.pdf"},
        "texts": [{"text": "配達⽇", "prov": [{"page_no": 1}]}],
        "tables": [
            {
                "prov": [{"page_no": 1}],
                "data": {
                    "table_cells": [
                        {"start_row_offset_idx": 0, "start_col_offset_idx": 0, "text": KANGXI_ROW}
                    ]
                },
            }
        ],
    }

    texts = [c["text"] for c in extract_relevant(doc)["chunks"]]

    assert texts == ["配達日", "11 月 27 日 ( 木 )"]
