"""File handling utilities for OpenRAG"""
import os
import re
import tempfile
from contextlib import contextmanager
from typing import Optional
from urllib.parse import unquote, urlparse


@contextmanager
def auto_cleanup_tempfile(suffix: Optional[str] = None, prefix: Optional[str] = None, dir: Optional[str] = None):
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
    """Clean filename and ensure correct extension.

    If the MIME type maps to a known extension, it is enforced.
    If the MIME type is unknown, the original filename (and its extension) is kept as-is
    rather than appending a meaningless .bin suffix.
    """
    clean_name = filename.replace(" ", "_").replace("/", "_")
    suffix = get_file_extension(mimetype)
    if suffix is None:
        # Unknown type — keep whatever extension the file already has
        return clean_name
    if not clean_name.lower().endswith(suffix.lower()):
        return clean_name + suffix
    return clean_name


# Characters that are unsafe in filenames across Linux, macOS, and Windows
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_UNDERSCORE = re.compile(r'_+')


def sanitize_filename(url: str, fallback: str = "document", max_length: int = 200) -> str:
    """
    Derive a safe filename from a URL for use during document ingestion.

    Decodes percent-encoding, extracts the last path segment, strips query
    strings and fragments, and removes characters that are unsafe on any
    major OS filesystem.

    Examples::

        sanitize_filename("https://example.com/docs/my%20report.pdf")
        # "my_report.pdf"

        sanitize_filename("https://example.com/blog/post?id=42#section")
        # "post"

        sanitize_filename("https://example.com/")
        # "document"

    Args:
        url:        The source URL to derive a filename from.
        fallback:   Name to use when no usable path segment can be found.
        max_length: Maximum number of characters in the returned filename
                    (excluding extension). Defaults to 200.

    Returns:
        A cleaned filename string safe for use on Linux, macOS, and Windows.
    """
    try:
        parsed = urlparse(url)
        # Take the last non-empty path segment, ignoring query/fragment
        path_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        # Decode percent-encoding (e.g. %20 → space)
        path_segment = unquote(path_segment)
    except Exception:
        path_segment = ""

    if not path_segment:
        return fallback

    # Replace spaces and unsafe characters with underscores
    name = path_segment.replace(" ", "_")
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    # Collapse consecutive underscores
    name = _MULTI_UNDERSCORE.sub("_", name).strip("_")

    if not name:
        return fallback

    # Respect max_length while preserving the extension if present
    if "." in name:
        stem, _, ext = name.rpartition(".")
        stem = stem[:max_length]
        name = f"{stem}.{ext}" if stem else fallback
    else:
        name = name[:max_length]

    return name or fallback
