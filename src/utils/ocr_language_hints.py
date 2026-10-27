"""Warn when ingested text is in a script whose OCR language isn't selected.

OCR only recognizes the languages in `knowledge.ocr_languages`. Scanned text in
any other script is mostly dropped without a trace, but some of it can survive
(Apple Vision reads Cyrillic with English selected, and a page may mix a text
layer with scanned parts). When it does, its script tells us which language
the user should add. Text that vanished entirely can't be detected this way.

Scripts are identified from Unicode ranges, which is cheap and needs no model.
Latin-script languages (French, German, ...) can't be told apart from English
this way and are not reported.
"""

from collections.abc import Iterable

# Fewer characters than this in a script is treated as OCR noise.
MIN_SCRIPT_CHARS = 20

# Share of kana among kana + Han characters above which Han text is Japanese.
# Japanese prose runs well above this; a stray kana in Chinese text does not.
JAPANESE_KANA_SHARE = 0.1

_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "hangul": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)),
    "arabic": (
        (0x0600, 0x06FF),
        (0x0750, 0x077F),
        (0x08A0, 0x08FF),
        (0xFB50, 0xFDFF),
        (0xFE70, 0xFEFF),
    ),
    "thai": ((0x0E00, 0x0E7F),),
    "cyrillic": ((0x0400, 0x052F),),
    "kana": ((0x3040, 0x30FF), (0x31F0, 0x31FF)),
    "han": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF)),
}

# Language label shown to the user, and the OCR language codes (neutral codes,
# as stored in knowledge.ocr_languages) any one of which covers it.
_LANGUAGES: dict[str, tuple[str, frozenset[str]]] = {
    "hangul": ("Korean", frozenset({"ko"})),
    "arabic": ("Arabic", frozenset({"ar"})),
    "thai": ("Thai", frozenset({"th"})),
    "cyrillic": ("Russian or Ukrainian", frozenset({"ru", "uk"})),
    "japanese": ("Japanese", frozenset({"ja"})),
    # Han characters alone don't say which language they belong to.
    "chinese": ("Chinese", frozenset({"zh-Hans", "zh-Hant", "ja"})),
}


def _script_of(char: str) -> str | None:
    code = ord(char)
    for script, ranges in _RANGES.items():
        if any(low <= code <= high for low, high in ranges):
            return script
    return None


def _count_scripts(texts: Iterable[str]) -> dict[str, int]:
    counts = dict.fromkeys(_RANGES, 0)
    for text in texts:
        for char in text:
            # Everything below U+0400 is Latin, digits or punctuation.
            if ord(char) < 0x0400:
                continue
            script = _script_of(char)
            if script:
                counts[script] += 1
    return counts


def _found_languages(counts: dict[str, int]) -> dict[str, int]:
    """Character count per language key, with Han assigned to Japanese or Chinese."""
    found = {key: counts[key] for key in ("hangul", "arabic", "thai", "cyrillic")}
    kana, han = counts["kana"], counts["han"]
    if kana + han and kana / (kana + han) >= JAPANESE_KANA_SHARE:
        found["japanese"] = kana + han
    else:
        found["chinese"] = han
    return found


def _join(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def ocr_language_warning(texts: Iterable[str], ocr_languages: list[str]) -> str | None:
    """A user-facing warning naming languages found in `texts` but not selected
    for OCR, or None when there is nothing to report.

    An empty `ocr_languages` counts as English only, which is what the engines
    fall back to.
    """
    selected = set(ocr_languages)
    missing = []
    for key, count in _found_languages(_count_scripts(texts)).items():
        label, covering = _LANGUAGES[key]
        if count >= MIN_SCRIPT_CHARS and not covering & selected:
            missing.append(label)
    if not missing:
        return None
    languages = _join(missing)
    return (
        f"This file contains {languages} text, which isn't selected under OCR languages. "
        f"If it has scanned pages, some of that text may be missing: add {languages} "
        "in Settings > Ingest > Advanced OCR Settings and re-ingest the file."
    )
