"""Utility functions for showing error notifications with diagnostics button."""

from typing import Literal, Callable

from textual.app import App


def notify_with_diagnostics(
    app: App,
    message: str,
    severity: Literal["information", "warning", "error"] = "error",
    timeout: float | None = None,
) -> None:
    """Show a notification with a button to open the diagnostics screen.

    Args:
        app: The Textual app
        message: The notification message
        severity: The notification severity
        timeout: The notification timeout in seconds (None for default 20s)
    """
    # First show the notification
    app.notify(message, severity=severity, timeout=timeout)

    # Then add a button to open diagnostics screen
    def open_diagnostics() -> None:
        from ..screens.diagnostics import DiagnosticsScreen

        app.push_screen(DiagnosticsScreen())

    # Add a separate notification with just the button
    app.notify(
        "Click to view diagnostics",
        severity="information",
        timeout=timeout,
        title="Diagnostics",
    )


# Made with Bob
