"""Clipboard helper utilities for the TUI."""

from __future__ import annotations

import platform
import subprocess
from typing import Tuple


def copy_text_to_clipboard(text: str) -> Tuple[bool, str]:
    """Copy ``text`` to the system clipboard.

    Returns a tuple of (success, message) so callers can surface feedback to users.
    """
    # Try optional dependency first for cross-platform consistency
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True, "Copied to clipboard"
    except ImportError:
        # Fall back to platform-specific commands
        pass
    except Exception as exc:  # pragma: no cover - defensive catch for pyperclip edge cases
        return False, f"Clipboard error: {exc}"

    system = platform.system()

    try:
        if system == "Darwin":
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            process.communicate(input=text)
            return True, "Copied to clipboard"
        if system == "Windows":
            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, text=True)
            process.communicate(input=text)
            return True, "Copied to clipboard"
        if system == "Linux":
            for command in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                try:
                    process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True)
                    process.communicate(input=text)
                    return True, "Copied to clipboard"
                except FileNotFoundError:
                    continue
            return False, "Clipboard utilities not found. Install xclip or xsel."
        return False, "Clipboard not supported on this platform"
    except Exception as exc:  # pragma: no cover - subprocess errors
        return False, f"Clipboard error: {exc}"

