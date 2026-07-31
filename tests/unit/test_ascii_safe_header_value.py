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


# ---------------------------------------------------------------------------
# FileNet deployment-config knobs travel to the flow as global variables
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from utils.langflow_headers import add_provider_credentials_to_headers  # noqa: E402

ICN_TEMPLATE = (
    "https://cpd.example.com/icn/navigator/bookmark.jsp"
    "?docid={class}%2C%7BB9F063B1-E6F4-46DD-BEF4-D5E57EDCA08F%7D%2C{id_braced}"
    "&mimeType={mimetype}&template_name={class}"
)


def _empty_provider_config():
    """A config with no providers set, so only the FileNet vars are exercised."""
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key=None),
            anthropic=SimpleNamespace(api_key=None),
            watsonx=SimpleNamespace(api_key=None, project_id=None),
            ollama=SimpleNamespace(endpoint=None),
        )
    )


def _build_headers(monkeypatch, **env):
    for var in ("OPENRAG_FILENET_VIEWER_URL_TEMPLATE", "OPENRAG_FILENET_SNIPPET_CHAR_CAP"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    headers: dict[str, str] = {}
    asyncio.run(add_provider_credentials_to_headers(headers, _empty_provider_config()))
    return headers


def test_filenet_vars_absent_when_unset(monkeypatch):
    """No env var => no global variable => the flow component uses its defaults."""
    headers = _build_headers(monkeypatch)
    assert "X-LANGFLOW-GLOBAL-VAR-FILENET_VIEWER_URL_TEMPLATE" not in headers
    assert "X-LANGFLOW-GLOBAL-VAR-FILENET_SNIPPET_CHAR_CAP" not in headers


def test_filenet_vars_forwarded_when_set(monkeypatch):
    headers = _build_headers(
        monkeypatch,
        OPENRAG_FILENET_VIEWER_URL_TEMPLATE=ICN_TEMPLATE,
        OPENRAG_FILENET_SNIPPET_CHAR_CAP="20000",
    )
    assert headers["X-LANGFLOW-GLOBAL-VAR-FILENET_VIEWER_URL_TEMPLATE"] == ICN_TEMPLATE
    assert headers["X-LANGFLOW-GLOBAL-VAR-FILENET_SNIPPET_CHAR_CAP"] == "20000"


def test_filenet_snippet_cap_rejected_before_reaching_the_flow(monkeypatch):
    headers = _build_headers(monkeypatch, OPENRAG_FILENET_SNIPPET_CHAR_CAP="lots")
    assert "X-LANGFLOW-GLOBAL-VAR-FILENET_SNIPPET_CHAR_CAP" not in headers


def test_filenet_viewer_template_header_is_ascii_encodable(monkeypatch):
    """A non-ASCII character would otherwise raise before the request is sent."""
    headers = _build_headers(
        monkeypatch, OPENRAG_FILENET_VIEWER_URL_TEMPLATE="https://x/café/{id}"
    )
    value = headers["X-LANGFLOW-GLOBAL-VAR-FILENET_VIEWER_URL_TEMPLATE"]
    value.encode("ascii")  # must not raise
    httpx.Headers({"X-LANGFLOW-GLOBAL-VAR-FILENET_VIEWER_URL_TEMPLATE": value})
