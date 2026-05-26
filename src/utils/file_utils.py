"""File handling utilities for OpenRAG"""

import os
import tempfile
from contextlib import contextmanager


@contextmanager
def auto_cleanup_tempfile(
    suffix: str | None = None, prefix: str | None = None, dir: str | None = None
):
    """
    Context manager for temporary files that automatically cleans up.

    Unlike tempfile.NamedTemporaryFile with delete=True, this keeps the file
    on disk for the duration of the context, making it safe for async operations.

    Usage:
        with auto_cleanup_tempfile(suffix=".pdf") as tmp_path:
            # Write to the file
            with open(tmp_path, 'wb') as f:
                f.write(content)
            # Use tmp_path for processing
            result = await process_file(tmp_path)
        # File is automatically deleted here

    Args:
        suffix: Optional file suffix/extension (e.g., ".pdf")
        prefix: Optional file prefix
        dir: Optional directory for temp file

    Yields:
        str: Path to the temporary file
    """
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=dir)
    try:
        os.close(fd)  # Close the file descriptor immediately
        yield path
    finally:
        # Always clean up, even if an exception occurred
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            # Silently ignore cleanup errors
            pass


def safe_unlink(path: str) -> None:
    """
    Safely delete a file, ignoring errors if it doesn't exist.

    Args:
        path: Path to the file to delete
    """
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        # Silently ignore errors
        pass


def get_file_extension(mimetype: str) -> str:
    """Get file extension based on MIME type. Returns None if the type is unknown."""
    mime_to_ext = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.ms-powerpoint": ".ppt",
        "text/plain": ".txt",
        "text/markdown": ".md",
        "text/x-markdown": ".md",
        "text/html": ".html",
        "text/csv": ".csv",
        "application/json": ".json",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "application/rtf": ".rtf",
        "application/vnd.google-apps.document": ".pdf",  # Exported as PDF
        "application/vnd.google-apps.presentation": ".pdf",
        "application/vnd.google-apps.spreadsheet": ".pdf",
    }
    return mime_to_ext.get(mimetype)


def clean_connector_filename(filename: str, mimetype: str) -> str:
    """Ensure the filename ends with the extension that matches its MIME type.

    The original name is preserved verbatim (spaces, slashes, casing) so that
    connector-indexed filenames match what the user sees in the source system
    and what a local upload of the same file would index as. Only the
    extension is enforced, and only when the MIME type maps to one — for an
    unknown MIME type, the original filename and extension are kept.
    """
    suffix = get_file_extension(mimetype)
    if suffix is None:
        return filename
    if not filename.lower().endswith(suffix.lower()):
        return filename + suffix
    return filename


def langflow_safe_filename_and_mimetype(filename: str, mimetype: str | None) -> tuple[str, str]:
    """Apply the .txt -> .md workaround for Langflow ingestion.

    Langflow's docling component fails on text/plain (see commit f6b9fe0).
    The workaround is to rename .txt files to .md with text/markdown before
    handing the file to Langflow. Centralised here so every Langflow-upload
    site applies it identically — local user uploads, connector-driven
    ingestion, and the direct upload route.

    Returns the (possibly rewritten) (filename, mimetype) pair. Pass-through
    for all other extensions; falls back to application/octet-stream when
    mimetype is missing.
    """
    safe_mimetype = mimetype or "application/octet-stream"
    if filename and filename.lower().endswith(".txt"):
        return filename[:-4] + ".md", "text/markdown"
    return filename, safe_mimetype


def get_filename_aliases(filename: str) -> list[str]:
    """Return equivalent filename variants used by ingestion/indexing.

    Legacy Langflow ingest indexes `.txt` uploads as `.md` (see
    `LangflowFileProcessor`). The alias always uses a lowercase extension
    to match the rename behavior:
      `original_filename[:-4] + ".md"`
    So `"FOO.TXT"` aliases to `"FOO.md"`, not `"FOO.MD"`.

    This helper keeps duplicate detection/deletion consistent by checking
    both `.txt` and `.md` forms.
    """
    normalized = (filename or "").strip()
    if not normalized:
        return []

    aliases = [normalized]
    lower_name = normalized.lower()

    if lower_name.endswith(".txt"):
        aliases.append(normalized[:-4] + ".md")
    elif lower_name.endswith(".md"):
        aliases.append(normalized[:-3] + ".txt")

    # Mirror clean_connector_filename's space/slash -> underscore so lookups also
    # match files indexed through a connector ingestion path.
    aliases.extend(name.replace(" ", "_").replace("/", "_") for name in list(aliases))

    # Keep order stable while removing duplicates.
    return list(dict.fromkeys(aliases))
