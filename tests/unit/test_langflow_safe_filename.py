"""Pin the .txt -> .md workaround applied at every Langflow upload site.

Langflow's docling component fails on text/plain (commit f6b9fe0). The
helper at `src/utils/file_utils.py::langflow_safe_filename_and_mimetype` is
the single source of truth for that rename — every place that builds a
file_tuple for `LangflowFileService.upload_user_file` must call it.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from utils.file_utils import langflow_safe_filename_and_mimetype  # noqa: E402


@pytest.mark.parametrize(
    "filename,mimetype,expected_filename,expected_mimetype",
    [
        # Core rule: .txt becomes .md, mimetype switches to text/markdown.
        ("foo.txt", "text/plain", "foo.md", "text/markdown"),
        # Case-insensitive: extension match ignores case but preserves the
        # original stem case; only the extension is rewritten to ".md".
        ("FOO.TXT", "text/plain", "FOO.md", "text/markdown"),
        ("Report.Txt", "text/plain", "Report.md", "text/markdown"),
        # Pass-through: .md is already fine.
        ("notes.md", "text/markdown", "notes.md", "text/markdown"),
        # Pass-through: unrelated extensions.
        ("doc.pdf", "application/pdf", "doc.pdf", "application/pdf"),
        ("sheet.csv", "text/csv", "sheet.csv", "text/csv"),
        # Missing mimetype: still rewrite .txt to .md (the bug we're fixing is
        # about Langflow tripping on text/plain — once we rewrite, we own the
        # mimetype). Non-.txt without mimetype gets the octet-stream default.
        ("foo.txt", None, "foo.md", "text/markdown"),
        ("foo.pdf", None, "foo.pdf", "application/octet-stream"),
        # Defensive: empty filename returns the octet-stream default, never crashes.
        ("", "text/plain", "", "text/plain"),
        ("", None, "", "application/octet-stream"),
    ],
)
def test_helper_applies_txt_to_md_rule(filename, mimetype, expected_filename, expected_mimetype):
    out_filename, out_mimetype = langflow_safe_filename_and_mimetype(filename, mimetype)
    assert out_filename == expected_filename
    assert out_mimetype == expected_mimetype


def test_helper_does_not_match_txt_substring_in_middle_of_name():
    """`.txt` must only match as a SUFFIX, otherwise filenames like
    `notes.txt.bak` or `mytxt.pdf` would be mangled."""
    # A real edge case: file genuinely named `something.txt.bak` is NOT a .txt.
    out_filename, out_mimetype = langflow_safe_filename_and_mimetype(
        "notes.txt.bak", "application/octet-stream"
    )
    assert out_filename == "notes.txt.bak"
    assert out_mimetype == "application/octet-stream"

    # Different real case: `mytxt.pdf` — txt is just part of the stem.
    out_filename, out_mimetype = langflow_safe_filename_and_mimetype("mytxt.pdf", "application/pdf")
    assert out_filename == "mytxt.pdf"
    assert out_mimetype == "application/pdf"
