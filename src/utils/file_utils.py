"""File handling utilities for OpenRAG"""

import os
import tempfile
from contextlib import contextmanager
from typing import Optional


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