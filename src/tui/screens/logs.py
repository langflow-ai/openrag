"""Logs viewing screen for OpenRAG TUI."""

import asyncio
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, TextArea
from textual.timer import Timer
from rich.text import Text

from ..managers.container_manager import ContainerManager
from ..managers.docling_manager import DoclingManager


class LogsScreen(Screen):
    """Logs viewing and monitoring screen."""

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
    ]

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
        self.logs_area = None
        self.following = False
        self.follow_task = None
        self.auto_scroll = True

    def compose(self) -> ComposeResult:
        """Create the logs screen layout."""
        yield Container(
            Vertical(
                Static(f"Service Logs: {self.current_service}", id="logs-title"),
                self._create_logs_area(),
                id="logs-content",
            ),
            id="main-container",
        )
        yield Footer()

    def _create_logs_area(self) -> TextArea:
        """Create the logs text area."""
        self.logs_area = TextArea(
            text="Loading logs...",
            read_only=True,
            show_line_numbers=False,
            id="logs-area",
        )
        return self.logs_area

    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        # Set the correct service in the select widget after a brief delay
        try:
            select = self.query_one("#service-select")
            # Set a default first, then set the desired value
            select.value = "openrag-backend"
            if self.current_service in [
                "openrag-backend",
                "openrag-frontend",
                "opensearch",
                "langflow",
                "dashboards",
            ]:
                select.value = self.current_service
        except Exception as e:
            # If setting the service fails, just use the default
            pass

        await self._load_logs()

        # Focus the logs area since there are no buttons
        try:
            self.logs_area.focus()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        self._stop_following()

    async def _load_logs(self, lines: int = 200) -> None:
        """Load recent logs for the current service."""
        # Special handling for docling-serve
        if self.current_service == "docling-serve":
            success, logs = self.docling_manager.get_logs(lines)
            if success:
                self.logs_area.text = logs
                # Scroll to bottom if auto scroll is enabled
                if self.auto_scroll:
                    self.logs_area.scroll_end()
            else:
                self.logs_area.text = f"Failed to load logs: {logs}"
            return
            
        # Regular container services
        if not self.container_manager.is_available():
            self.logs_area.text = "No container runtime available"
            return

        success, logs = await self.container_manager.get_service_logs(
            self.current_service, lines
        )

        if success:
            self.logs_area.text = logs
            # Scroll to bottom if auto scroll is enabled
            if self.auto_scroll:
                self.logs_area.scroll_end()
        else:
            self.logs_area.text = f"Failed to load logs: {logs}"

    def _stop_following(self) -> None:
        """Stop following logs."""
        self.following = False
        if self.follow_task and not self.follow_task.is_finished:
            self.follow_task.cancel()

        # No button to update since we removed it

    async def _follow_logs(self) -> None:
        """Follow logs in real-time."""
        # Special handling for docling-serve
        if self.current_service == "docling-serve":
            try:
                async for log_lines in self.docling_manager.follow_logs():
                    if not self.following:
                        break
                    
                    # Update logs area with new content
                    current_text = self.logs_area.text
                    new_text = current_text + "\n" + log_lines if current_text else log_lines
                    
                    # Keep only last 1000 lines to prevent memory issues
                    lines = new_text.split("\n")
                    if len(lines) > 1000:
                        lines = lines[-1000:]
                        new_text = "\n".join(lines)
                    
                    self.logs_area.text = new_text
                    # Scroll to bottom if auto scroll is enabled
                    if self.auto_scroll:
                        self.logs_area.scroll_end()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                if self.following:  # Only show error if we're still supposed to be following
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

                # Append new line to logs area
                current_text = self.logs_area.text
                new_text = current_text + "\n" + log_line

                # Keep only last 1000 lines to prevent memory issues
                lines = new_text.split("\n")
                if len(lines) > 1000:
                    lines = lines[-1000:]
                    new_text = "\n".join(lines)

                self.logs_area.text = new_text
                # Scroll to bottom if auto scroll is enabled
                if self.auto_scroll:
                    self.logs_area.scroll_end()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if (
                self.following
            ):  # Only show error if we're still supposed to be following
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

            # Start following
            self.follow_task = self.run_worker(self._follow_logs(), exclusive=False)

    def action_clear(self) -> None:
        """Clear the logs area."""
        self.logs_area.text = ""

    def action_toggle_auto_scroll(self) -> None:
        """Toggle auto scroll on/off."""
        self.auto_scroll = not self.auto_scroll
        status = "enabled" if self.auto_scroll else "disabled"
        self.notify(f"Auto scroll {status}", severity="information")

    def action_scroll_top(self) -> None:
        """Scroll to the top of logs."""
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
        """Handle key presses that might be intercepted by TextArea."""
        key = event.key

        # Handle keys that TextArea might intercept
        if key == "ctrl+u":
            self.action_scroll_page_up()
            event.prevent_default()
        elif key == "ctrl+f":
            self.action_scroll_page_down()
            event.prevent_default()
        elif key.upper() == "G":
            self.action_scroll_bottom()
            event.prevent_default()

    def action_back(self) -> None:
        """Go back to previous screen."""
        self._stop_following()
        self.app.pop_screen()
