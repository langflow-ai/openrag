"""Pin the ASCII-safe HTTP header encoding used for Langflow global variables.

A non-ASCII filename or owner name placed into an ``X-Langflow-Global-Var-*``
header raised ``UnicodeEncodeError`` in httpx before the request was sent
(httpx requires ASCII-encodable header values). The helper at
`src/utils/langflow_headers.py::ascii_safe_header_value` percent-encodes only
non-ASCII values; ASCII passes through untouched.
"""

import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from utils.langflow_headers import ascii_safe_header_value  # noqa: E402


@pytest.mark.parametrize(
    "value,expected",
    [
        # ASCII passes through byte-for-byte, including spaces and slashes.
        ("report.pdf", "report.pdf"),
        ("my report (final).pdf", "my report (final).pdf"),
        ("a/b/c.txt", "a/b/c.txt"),
        ("", ""),
        # None coerces to empty string.
        (None, ""),
        # Non-string ASCII coerces via str().
        (123, "123"),
    ],
)
def test_ascii_values_pass_through(value, expected):
    assert ascii_safe_header_value(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "こんにちは こんにちは.pdf",  # Japanese (the reported crash)
        "José García.docx",  # accented owner name
        "файл.pdf",  # Cyrillic
        "emoji-📄.pdf",  # emoji
    ],
)
def test_non_ascii_values_become_ascii_encodable(value):
    encoded = ascii_safe_header_value(value)
    # The whole point: the result must survive httpx's ASCII encoding.
    encoded.encode("ascii")
    # It is percent-encoded, not silently dropped — the value is non-empty
    # and differs from the raw input.
    assert encoded
    assert encoded != value


def test_headers_dict_survives_httpx_normalization():
    """Regression: a header dict carrying non-ASCII owner metadata must build
    into httpx.Headers without raising (this is exactly where ingestion crashed).
    X-Langflow-Global-Var-FILENAME was removed; OWNER_NAME/OWNER_EMAIL are the
    remaining headers that can carry user-supplied non-ASCII values."""
    headers = {
        "X-Langflow-Global-Var-OWNER_NAME": ascii_safe_header_value("José García"),
        "X-Langflow-Global-Var-OWNER_EMAIL": ascii_safe_header_value("josé@例え.jp"),
    }
    # Previously raised UnicodeEncodeError here.
    httpx.Headers(headers)
