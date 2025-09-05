"""Welcome screen for OpenRAG TUI."""

import os
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from rich.text import Text
from rich.align import Align
from dotenv import load_dotenv

from ..managers.container_manager import ContainerManager, ServiceStatus
from ..managers.env_manager import EnvManager


class WelcomeScreen(Screen):
    """Initial welcome screen with setup options."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("enter", "default_action", "Continue"),
        ("1", "no_auth_setup", "Basic Setup"),
        ("2", "full_setup", "Advanced Setup"),
        ("3", "monitor", "Monitor Services"),
        ("4", "diagnostics", "Diagnostics"),
    ]

    def __init__(self):
        super().__init__()
        self.container_manager = ContainerManager()
        self.env_manager = EnvManager()
        self.services_running = False
        self.has_oauth_config = False
        self.default_button_id = "basic-setup-btn"
        self._state_checked = False

        # Load .env file if it exists
        load_dotenv()

    def compose(self) -> ComposeResult:
        """Create the welcome screen layout."""
        yield Container(
            Vertical(
                Static(self._create_welcome_text(), id="welcome-text"),
                self._create_dynamic_buttons(),
                id="welcome-container",
            ),
            id="main-container",
        )
        yield Footer()

    def _create_welcome_text(self) -> Text:
        """Create a minimal welcome message."""
        welcome_text = Text()
        ascii_art = """
██████╗ ██████╗ ███████╗███╗   ██╗██████╗  █████╗  ██████╗ 
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔══██╗██╔════╝ 
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██████╔╝███████║██║  ███╗
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██╗██╔══██║██║   ██║
╚██████╔╝██║     ███████╗██║ ╚████║██║  ██║██║  ██║╚██████╔╝
╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝
"""
        welcome_text.append(ascii_art, style="bold blue")
        welcome_text.append("Terminal User Interface for OpenRAG\n\n", style="dim")

        if self.services_running:
            welcome_text.append(
                "✓ Services are currently running\n\n", style="bold green"
            )
        elif self.has_oauth_config:
            welcome_text.append(
                "OAuth credentials detected — Advanced Setup recommended\n\n",
                style="bold green",
            )
        else:
            welcome_text.append("Select a setup below to continue\n\n", style="white")
        return welcome_text

    def _create_dynamic_buttons(self) -> Horizontal:
        """Create buttons based on current state."""
        # Check OAuth config early to determine which buttons to show
        has_oauth = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

        buttons = []

        if self.services_running:
            # Services running - only show monitor
            buttons.append(
                Button("Monitor Services", variant="success", id="monitor-btn")
            )
        else:
            # Services not running - show setup options
            if has_oauth:
                # Only show advanced setup if OAuth is configured
                buttons.append(
                    Button("Advanced Setup", variant="success", id="advanced-setup-btn")
                )
            else:
                # Only show basic setup if no OAuth
                buttons.append(
                    Button("Basic Setup", variant="success", id="basic-setup-btn")
                )

            # Always show monitor option
            buttons.append(
                Button("Monitor Services", variant="default", id="monitor-btn")
            )

        return Horizontal(*buttons, classes="button-row")

    async def on_mount(self) -> None:
        """Initialize screen state when mounted."""
        # Check if services are running
        if self.container_manager.is_available():
            services = await self.container_manager.get_service_status()
            running_services = [
                s.name for s in services.values() if s.status == ServiceStatus.RUNNING
            ]
            self.services_running = len(running_services) > 0

        # Check for OAuth configuration
        self.has_oauth_config = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

        # Set default button focus
        if self.services_running:
            self.default_button_id = "monitor-btn"
        elif self.has_oauth_config:
            self.default_button_id = "advanced-setup-btn"
        else:
            self.default_button_id = "basic-setup-btn"

        # Update the welcome text and recompose with new state
        try:
            welcome_widget = self.query_one("#welcome-text")
            welcome_widget.update(
                self._create_welcome_text()
            )  # This is fine for Static widgets

            # Focus the appropriate button
            if self.services_running:
                try:
                    self.query_one("#monitor-btn").focus()
                except:
                    pass
            elif self.has_oauth_config:
                try:
                    self.query_one("#advanced-setup-btn").focus()
                except:
                    pass
            else:
                try:
                    self.query_one("#basic-setup-btn").focus()
                except:
                    pass

        except:
            pass  # Widgets might not be mounted yet

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "basic-setup-btn":
            self.action_no_auth_setup()
        elif event.button.id == "advanced-setup-btn":
            self.action_full_setup()
        elif event.button.id == "monitor-btn":
            self.action_monitor()
        elif event.button.id == "diagnostics-btn":
            self.action_diagnostics()

    def action_default_action(self) -> None:
        """Handle Enter key - go to default action based on state."""
        if self.services_running:
            self.action_monitor()
        elif self.has_oauth_config:
            self.action_full_setup()
        else:
            self.action_no_auth_setup()

    def action_no_auth_setup(self) -> None:
        """Switch to basic configuration screen."""
        from .config import ConfigScreen

        self.app.push_screen(ConfigScreen(mode="no_auth"))

    def action_full_setup(self) -> None:
        """Switch to advanced configuration screen."""
        from .config import ConfigScreen

        self.app.push_screen(ConfigScreen(mode="full"))

    def action_monitor(self) -> None:
        """Switch to monitoring screen."""
        from .monitor import MonitorScreen

        self.app.push_screen(MonitorScreen())

    def action_diagnostics(self) -> None:
        """Switch to diagnostics screen."""
        from .diagnostics import DiagnosticsScreen

        self.app.push_screen(DiagnosticsScreen())

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()
