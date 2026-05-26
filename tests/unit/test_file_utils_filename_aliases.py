from utils.file_utils import clean_connector_filename, get_filename_aliases


def test_empty_input_returns_empty_list():
    assert get_filename_aliases("") == []
    assert get_filename_aliases(None) == []
    assert get_filename_aliases("   ") == []


def test_plain_filename_returns_single_alias():
    assert get_filename_aliases("Report.pdf") == ["Report.pdf"]


def test_txt_md_swap_preserved():
    aliases = get_filename_aliases("notes.txt")
    assert aliases == ["notes.txt", "notes.md"]

    aliases = get_filename_aliases("notes.md")
    assert aliases == ["notes.md", "notes.txt"]


def test_spaces_get_underscore_variant():
    """Connector ingestion replaces spaces with underscores; lookup must match
    both the original and sanitized form so a SharePoint-ingested
    'Q1 Report.pdf' (indexed as 'Q1_Report.pdf') is detected when the user
    re-uploads it locally with the original name."""
    aliases = get_filename_aliases("Q1 Report.pdf")
    assert "Q1 Report.pdf" in aliases
    assert "Q1_Report.pdf" in aliases


def test_slashes_get_underscore_variant():
    aliases = get_filename_aliases("folder/file.pdf")
    assert "folder/file.pdf" in aliases
    assert "folder_file.pdf" in aliases


def test_spaces_combined_with_txt_md_swap():
    aliases = get_filename_aliases("My Notes.txt")
    assert set(aliases) == {
        "My Notes.txt",
        "My Notes.md",
        "My_Notes.txt",
        "My_Notes.md",
    }


def test_order_stable_and_deduped():
    """Original first, then variants. Names without spaces/slashes must not
    produce duplicate entries from the sanitization pass."""
    aliases = get_filename_aliases("report.txt")
    assert aliases == ["report.txt", "report.md"]

    aliases = get_filename_aliases("My Notes.txt")
    assert aliases[0] == "My Notes.txt"
    assert len(aliases) == len(set(aliases))


def test_clean_connector_filename_preserves_spaces_and_slashes():
    """Spaces and slashes must survive so connector-indexed filenames match
    what a local upload of the same file would index as."""
    assert clean_connector_filename("My Report.pdf", "application/pdf") == "My Report.pdf"
    assert clean_connector_filename("docs/file.txt", "text/plain") == "docs/file.txt"


def test_clean_connector_filename_enforces_mime_extension():
    """Google Docs / Slides / Sheets export as PDF — the suffix must be added
    when the name doesn't already end with the MIME-mapped extension."""
    assert (
        clean_connector_filename("untitled", "application/vnd.google-apps.document")
        == "untitled.pdf"
    )
    # Existing matching extension is not duplicated.
    assert (
        clean_connector_filename("untitled.pdf", "application/vnd.google-apps.document")
        == "untitled.pdf"
    )


def test_clean_connector_filename_unknown_mime_keeps_filename():
    assert clean_connector_filename("data.bin", "application/x-unknown") == "data.bin"
