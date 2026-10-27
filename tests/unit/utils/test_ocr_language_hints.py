"""Tests for the ingest-time warning about text in an unselected OCR language."""

from utils.ocr_language_hints import ocr_language_warning

KOREAN = "이 문서는 다국어 문서 테스트입니다. 이미지에 있는 텍스트를 정확하게 인식하세요."
ARABIC = "هذا اختبار لمستند متعدد اللغات. يُرجى التعرّف على النص الموجود في الصورة بدقة."
RUSSIAN = "Это тест многоязычного документа. Пожалуйста, правильно распознайте текст."
THAI = "นี่คือการทดสอบเอกสารหลายภาษา โปรดอ่านข้อความในภาพให้ถูกต้อง"
JAPANESE = "これは多言語文書のテストです。画像内のテキストを正確に認識してください。"
CHINESE = "这是一个多语言文档测试。请准确识别图像中的文字内容和所有的段落。"
ENGLISH = "The Leave Policy document outlines the company's guidelines for leave."


def test_english_only_text_has_no_warning():
    assert ocr_language_warning([ENGLISH], ["en"]) is None


def test_warns_when_korean_is_found_but_not_selected():
    warning = ocr_language_warning([ENGLISH, KOREAN], ["en"])

    assert warning is not None
    assert "Korean" in warning


def test_no_warning_when_the_language_is_selected():
    assert ocr_language_warning([KOREAN], ["ko", "en"]) is None


def test_names_every_unselected_language():
    warning = ocr_language_warning([ARABIC, THAI], ["en"])

    assert "Arabic" in warning
    assert "Thai" in warning


def test_either_cyrillic_language_covers_cyrillic_text():
    """Russian and Ukrainian share a script; selecting either one is enough."""
    assert ocr_language_warning([RUSSIAN], ["uk", "en"]) is None
    assert "Russian or Ukrainian" in ocr_language_warning([RUSSIAN], ["en"])


def test_kana_is_reported_as_japanese_not_chinese():
    warning = ocr_language_warning([JAPANESE], ["en"])

    assert "Japanese" in warning
    assert "Chinese" not in warning


def test_han_without_kana_is_reported_as_chinese():
    warning = ocr_language_warning([CHINESE], ["en"])

    assert "Chinese" in warning
    assert "Japanese" not in warning


def test_any_han_language_covers_han_text():
    """Han characters alone can't say which language they are; any of the three will do."""
    for selected in (["zh-Hans"], ["zh-Hant"], ["ja"]):
        assert ocr_language_warning([CHINESE], selected) is None


def test_a_few_stray_characters_are_noise():
    """OCR of a Latin page can emit an odd glyph; that is not a language."""
    assert ocr_language_warning([ENGLISH + " Ж ٥ 가"], ["en"]) is None


def test_counts_characters_across_chunks():
    """A language split thinly over many chunks is still found."""
    chunks = [KOREAN[i : i + 5] for i in range(0, len(KOREAN), 5)]

    assert "Korean" in ocr_language_warning(chunks, ["en"])


def test_empty_selection_counts_as_english_only():
    assert "Korean" in ocr_language_warning([KOREAN], [])


def test_no_text_has_no_warning():
    assert ocr_language_warning([], ["en"]) is None
