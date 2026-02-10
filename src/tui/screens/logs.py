"""Logs viewing screen for OpenRAG TUI."""

import asyncio
import re
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Log
from rich.text import Text

from ..managers.container_manager import ContainerManager
from ..managers.docling_manager import DoclingManager
from ..utils.clipboard import copy_text_to_clipboard

# Regex to strip ANSI escape sequences
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class LogsScreen(Screen):
    """Logs viewing and monitoring screen."""

    CSS = """
    #main-container {
        height: 1fr;
    }

    #logs-content {
        height: 1fr;
        padding: 1 1 0 1;
    }

    #logs-area {
        height: 1fr;
        min-height: 30;
    }

    #logs-button-row {
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "back", "Back"),
        ("f", "follow", "Follow Logs"),
        ("c", "clear", "Clear"),
        ("r", "refresh", "Refresh"),
        ("a", "toggle_auto_scroll", "Toggle Auto Scroll"),
        ("g", "scroll_top", "Go to Top"),
        ("G", "scroll_bottom", "Go to Bottom"),
        ("j", "scroll_down", "Scroll Down"),
        ("k", "scroll_up", "Scroll Up"),
        ("ctrl+u", "scroll_page_up", "Page Up"),
        ("ctrl+f", "scroll_page_down", "Page Down"),
        ("ctrl+c", "copy_logs", "Copy Logs"),
    ]

    # Maximum lines to keep in the log widget
    MAX_LOG_LINES = 1000

    def __init__(self, initial_service: str = "openrag-backend"):
        super().__init__()
        self.container_manager = ContainerManager()
        self.docling_manager = DoclingManager()

        # Validate the initial service against available options
        valid_services = [
            "openrag-backend",
            "openrag-frontend",
            "opensearch",
            "langflow",
            "dashboards",
            "docling-serve",  # Add docling-serve as a valid service
        ]
        if initial_service not in valid_services:
            initial_service = "openrag-backend"  # fallback

        self.current_service = initial_service
        self.logs_area: Log | None = None
        self.following = False
        self.follow_task = None
        self._status_task = None
        # Track log content for copy functionality
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        """Create the logs screen layout."""
        with Container(id="main-container"):
            with Vertical(id="logs-content"):
                yield Static(f"Service Logs: {self.current_service}", id="logs-title")
                yield self._create_logs_area()
                with Horizontal(id="logs-button-row"):
                    yield Button("Copy to Clipboard", variant="default", id="copy-btn")
                    yield Static("", id="copy-status", classes="copy-indicator")
        yield Footer()

    def _create_logs_area(self) -> Log:
        """Create the logs widget."""
        self.logs_area = Log(
            id="logs-area",
            max_lines=self.MAX_LOG_LINES,
            auto_scroll=True,
        )
        return self.logs_area

    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        await self._load_logs()

        # Start following logs by default
        if not self.following:
            self.action_follow()

        # Focus the logs area
        try:
            self.logs_area.focus()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        self._stop_following()
        if self._status_task:
            self._status_task.cancel()
            self._status_task = None

    async def _load_logs(self, lines: int = 200) -> None:
        """Load recent logs for the current service."""
        self.logs_area.clear()
        self._log_lines = []

        # Special handling for docling-serve
        if self.current_service == "docling-serve":
            success, logs = self.docling_manager.get_logs(lines)
            if success:
                for line in logs.split("\n"):
                    cleaned = self._clean_log_line(line)
                    if cleaned:
                        self.logs_area.write_line(cleaned)
                        self._log_lines.append(cleaned)
            else:
                self.logs_area.write_line(f"Failed to load logs: {logs}")
            return

        # Regular container services
        if not self.container_manager.is_available():
            self.logs_area.write_line("No container runtime available")
            return

        success, logs = await self.container_manager.get_service_logs(
            self.current_service, lines
        )

        if success:
            for line in logs.split("\n"):
                cleaned = self._clean_log_line(line)
                if cleaned:
                    self.logs_area.write_line(cleaned)
                    self._log_lines.append(cleaned)
        else:
            self.logs_area.write_line(f"Failed to load logs: {logs}")

    def _stop_following(self) -> None:
        """Stop following logs."""
        self.following = False
        if self.follow_task and not self.follow_task.is_finished:
            self.follow_task.cancel()

    def _clean_log_line(self, line: str) -> str:
        """Strip ANSI codes and handle carriage returns."""
        # Strip ANSI escape sequences
        line = ANSI_ESCAPE_RE.sub("", line)
        # Handle carriage returns - take only the last segment after \r
        if "\r" in line:
            line = line.split("\r")[-1]
        return line.rstrip()

    def _append_log_line(self, line: str) -> None:
        """Append a log line efficiently."""
        cleaned = self._clean_log_line(line)
        if cleaned:  # Skip empty lines after cleaning
            self.logs_area.write_line(cleaned)
            self._log_lines.append(cleaned)
            # Trim internal buffer to match max lines
            if len(self._log_lines) > self.MAX_LOG_LINES:
                self._log_lines = self._log_lines[-self.MAX_LOG_LINES:]

    async def _follow_logs(self) -> None:
        """Follow logs in real-time."""
        # Special handling for docling-serve
        if self.current_service == "docling-serve":
            try:
                async for log_lines in self.docling_manager.follow_logs():
                    if not self.following:
                        break

                    # Write each line directly - Log widget handles this efficiently
                    for line in log_lines.split("\n"):
                        if line:
                            self._append_log_line(line)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if self.following:
                    self.notify(f"Error following docling logs: {e}", severity="error")
            finally:
                self.following = False
            return

        # Regular container services
        if not self.container_manager.is_available():
            return

        try:
            async for log_line in self.container_manager.follow_service_logs(
                self.current_service
            ):
                if not self.following:
                    break

                # Write directly - Log widget handles this efficiently
                self._append_log_line(log_line)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.following:
                self.notify(f"Error following logs: {e}", severity="error")
        finally:
            self.following = False

    def action_refresh(self) -> None:
        """Refresh logs."""
        self._stop_following()
        self.run_worker(self._load_logs())

    def action_follow(self) -> None:
        """Toggle log following."""
        if self.following:
            self._stop_following()
        else:
            self.following = True
            self.follow_task = self.run_worker(self._follow_logs(), exclusive=False)

    def action_clear(self) -> None:
        """Clear the logs area."""
        self.logs_area.clear()
        self._log_lines = []

    def action_copy_logs(self) -> None:
        """Copy log content to the clipboard."""
        self._copy_logs_to_clipboard()

    def action_toggle_auto_scroll(self) -> None:
        """Toggle auto scroll on/off."""
        self.logs_area.auto_scroll = not self.logs_area.auto_scroll
        status = "enabled" if self.logs_area.auto_scroll else "disabled"
        self.notify(f"Auto scroll {status}", severity="information")

    def action_scroll_top(self) -> None:
        """Scroll to the top of logs."""
        # Disable auto-scroll when manually going to top, otherwise it snaps back
        if self.logs_area.auto_scroll:
            self.logs_area.auto_scroll = False
            self.notify("Auto scroll disabled", severity="information")
        self.logs_area.scroll_home()

    def action_scroll_bottom(self) -> None:
        """Scroll to the bottom of logs."""
        self.logs_area.scroll_end()

    def action_scroll_down(self) -> None:
        """Scroll down one line."""
        self.logs_area.scroll_down()

    def action_scroll_up(self) -> None:
        """Scroll up one line."""
        self.logs_area.scroll_up()

    def action_scroll_page_up(self) -> None:
        """Scroll up one page."""
        self.logs_area.scroll_page_up()

    def action_scroll_page_down(self) -> None:
        """Scroll down one page."""
        self.logs_area.scroll_page_down()

    def on_key(self, event) -> None:
        """Handle key presses that might be intercepted."""
        key = event.key

        if key == "ctrl+u":
            self.action_scroll_page_up()
            event.prevent_default()
        elif key == "ctrl+f":
            self.action_scroll_page_down()
            event.prevent_default()
        elif key == "G":  # Shift+G only
            self.action_scroll_bottom()
            event.prevent_default()

    def action_back(self) -> None:
        """Go back to previous screen."""
        self._stop_following()
        self.app.pop_screen()

    def _copy_logs_to_clipboard(self) -> None:
        """Copy the current log buffer to the clipboard."""
        if not self.logs_area:
            return

        content = "\n".join(self._log_lines)
        status_widget = self.query_one("#copy-status", Static)

        if not content.strip():
            message = "No logs to copy"
            self.notify(message, severity="warning")
            status_widget.update(Text("⚠ No logs to copy", style="bold yellow"))
            self._schedule_status_clear(status_widget)
            return

        success, message = copy_text_to_clipboard(content)
        self.notify(message, severity="information" if success else "error")
        prefix = "✓" if success else "❌"
        style = "bold green" if success else "bold red"
        status_widget.update(Text(f"{prefix} {message}", style=style))
        self._schedule_status_clear(status_widget)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "copy-btn":
            self._copy_logs_to_clipboard()

    def _schedule_status_clear(self, widget: Static, delay: float = 3.0) -> None:
        """Clear the status message after a short delay."""
        if self._status_task:
            self._status_task.cancel()

        async def _clear() -> None:
            try:
                await asyncio.sleep(delay)
                widget.update("")
            except asyncio.CancelledError:
                pass

        self._status_task = asyncio.create_task(_clear())
