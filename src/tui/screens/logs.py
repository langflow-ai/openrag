"""Logs viewing screen for OpenRAG TUI."""

import asyncio
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Select, TextArea
from textual.timer import Timer
from rich.text import Text

from ..managers.container_manager import ContainerManager


class LogsScreen(Screen):
    """Logs viewing and monitoring screen."""
    
    BINDINGS = [
        ("escape", "back", "Back"),
        ("f", "follow", "Follow Logs"),
        ("c", "clear", "Clear"),
        ("r", "refresh", "Refresh"),
    ]
    
    def __init__(self, initial_service: str = "openrag-backend"):
        super().__init__()
        self.container_manager = ContainerManager()
        self.current_service = initial_service
        self.logs_area = None
        self.following = False
        self.follow_task = None
    
    def compose(self) -> ComposeResult:
        """Create the logs screen layout."""
        yield Header()
        yield Container(
            Vertical(
                Static("Service Logs", id="logs-title"),
                Horizontal(
                    Static("Service:", classes="label"),
                    Select([
                        ("openrag-backend", "Backend"),
                        ("openrag-frontend", "Frontend"), 
                        ("opensearch", "OpenSearch"),
                        ("langflow", "Langflow"),
                        ("dashboards", "Dashboards")
                    ], value=self.current_service, id="service-select"),
                    Button("Refresh", variant="default", id="refresh-btn"),
                    Button("Follow", variant="primary", id="follow-btn"),
                    Button("Clear", variant="default", id="clear-btn"),
                    classes="controls-row"
                ),
                self._create_logs_area(),
                Horizontal(
                    Button("Back", variant="default", id="back-btn"),
                    classes="button-row"
                ),
                id="logs-content"
            ),
            id="main-container"
        )
        yield Footer()
    
    def _create_logs_area(self) -> TextArea:
        """Create the logs text area."""
        self.logs_area = TextArea(
            text="Loading logs...",
            read_only=True,
            show_line_numbers=False,
            id="logs-area"
        )
        return self.logs_area
    
    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        await self._load_logs()
    
    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        self._stop_following()
    
    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle service selection change."""
        if event.select.id == "service-select":
            self.current_service = event.value
            self._stop_following()
            self.run_worker(self._load_logs())
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-btn":
            self.action_refresh()
        elif event.button.id == "follow-btn":
            self.action_follow()
        elif event.button.id == "clear-btn":
            self.action_clear()
        elif event.button.id == "back-btn":
            self.action_back()
    
    async def _load_logs(self, lines: int = 200) -> None:
        """Load recent logs for the current service."""
        if not self.container_manager.is_available():
            self.logs_area.text = "No container runtime available"
            return
        
        success, logs = await self.container_manager.get_service_logs(self.current_service, lines)
        
        if success:
            self.logs_area.text = logs
            # Scroll to bottom
            self.logs_area.cursor_position = len(logs)
        else:
            self.logs_area.text = f"Failed to load logs: {logs}"
    
    def _stop_following(self) -> None:
        """Stop following logs."""
        self.following = False
        if self.follow_task and not self.follow_task.done():
            self.follow_task.cancel()
        
        # Update button text
        follow_btn = self.query_one("#follow-btn")
        follow_btn.label = "Follow"
        follow_btn.variant = "primary"
    
    async def _follow_logs(self) -> None:
        """Follow logs in real-time."""
        if not self.container_manager.is_available():
            return
        
        try:
            async for log_line in self.container_manager.follow_service_logs(self.current_service):
                if not self.following:
                    break
                
                # Append new line to logs area
                current_text = self.logs_area.text
                new_text = current_text + "\n" + log_line
                
                # Keep only last 1000 lines to prevent memory issues
                lines = new_text.split('\n')
                if len(lines) > 1000:
                    lines = lines[-1000:]
                    new_text = '\n'.join(lines)
                
                self.logs_area.text = new_text
                # Scroll to bottom
                self.logs_area.cursor_position = len(new_text)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.following:  # Only show error if we're still supposed to be following
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
            follow_btn = self.query_one("#follow-btn")
            follow_btn.label = "Stop Following"
            follow_btn.variant = "error"
            
            # Start following
            self.follow_task = self.run_worker(self._follow_logs(), exclusive=False)
    
    def action_clear(self) -> None:
        """Clear the logs area."""
        self.logs_area.text = ""
    
    def action_back(self) -> None:
        """Go back to previous screen."""
        self._stop_following()
        self.app.pop_screen()