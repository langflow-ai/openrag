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

from .. import __version__
from ..managers.container_manager import ContainerManager, ServiceStatus
from ..managers.env_manager import EnvManager
from ..managers.docling_manager import DoclingManager
from ..widgets.command_modal import CommandOutputModal


class WelcomeScreen(Screen):
    """Initial welcome screen with setup options."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("enter", "default_action", "Continue"),
        ("1", "no_auth_setup", "Basic Setup"),
        ("2", "full_setup", "Advanced Setup"),
        ("3", "monitor", "Status"),
        ("4", "diagnostics", "Diagnostics"),
        ("5", "start_stop_services", "Start/Stop Services"),
        ("6", "open_app", "Open App"),
    ]

    def __init__(self):
        super().__init__()
        self.container_manager = ContainerManager()
        self.env_manager = EnvManager()
        self.docling_manager = DoclingManager()
        self.services_running = False
        self.docling_running = False
        self.has_oauth_config = False
        self.default_button_id = "basic-setup-btn"
        self._state_checked = False

        # Load .env file if it exists
        load_dotenv()

        # Check OAuth config immediately
        self.has_oauth_config = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

    def compose(self) -> ComposeResult:
        """Create the welcome screen layout."""
        # Try to detect services synchronously before creating buttons
        self._detect_services_sync()

        yield Container(
            Vertical(
                Static(self._create_welcome_text(), id="welcome-text"),
                self._create_dynamic_buttons(),
                id="welcome-container",
            ),
            id="main-container",
        )
        yield Footer()

    def _detect_services_sync(self) -> None:
        """Synchronously detect if services are running."""
        if not self.container_manager.is_available():
            self.services_running = False
            self.docling_running = self.docling_manager.is_running()
            return

        try:
            # Use synchronous docker command to check services
            import subprocess
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                import json
                services = []

                # Try parsing as a single JSON array first (podman format)
                try:
                    parsed = json.loads(result.stdout.strip())
                    if isinstance(parsed, list):
                        services = parsed
                    else:
                        services = [parsed] if isinstance(parsed, dict) else []
                except json.JSONDecodeError:
                    # Fallback: try parsing line-by-line (docker format)
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            try:
                                service = json.loads(line)
                                if isinstance(service, dict):
                                    services.append(service)
                            except json.JSONDecodeError:
                                continue

                # Check if any services are running
                running_services = [s for s in services if isinstance(s, dict) and s.get('State') == 'running']
                self.services_running = len(running_services) > 0
            else:
                self.services_running = False
        except Exception:
            # Fallback to False if detection fails
            self.services_running = False

        # Update native service state as part of detection
        self.docling_running = self.docling_manager.is_running()

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
        welcome_text.append(ascii_art, style="bold white")
        welcome_text.append("Terminal User Interface for OpenRAG\n", style="dim")
        welcome_text.append(f"v{__version__}\n\n", style="white")

        # Check if all services are running
        all_services_running = self.services_running and self.docling_running

        if all_services_running:
            welcome_text.append(
                "✓ All services are running\n\n", style="bold green"
            )
        elif self.services_running or self.docling_running:
            welcome_text.append(
                "⚠ Some services are running\n\n", style="bold yellow"
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

        # Check if all services (native + container) are running
        all_services_running = self.services_running and self.docling_running

        if all_services_running:
            # All services running - show app link first, then stop all
            buttons.append(
                Button("Launch OpenRAG", variant="success", id="open-app-btn")
            )
            buttons.append(
                Button("Stop All Services", variant="error", id="stop-all-services-btn")
            )
        else:
            # Some or no services running - show setup options and start all
            if has_oauth:
                # If OAuth is configured, only show advanced setup
                buttons.append(
                    Button("Advanced Setup", variant="success", id="advanced-setup-btn")
                )
            else:
                # If no OAuth, show both options with basic as primary
                buttons.append(
                    Button("Basic Setup", variant="success", id="basic-setup-btn")
                )
                buttons.append(
                    Button("Advanced Setup", variant="default", id="advanced-setup-btn")
                )

            buttons.append(
                Button("Start All Services", variant="primary", id="start-all-services-btn")
            )

        # Always show status option
        buttons.append(
            Button("Status", variant="default", id="status-btn")
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
        else:
            self.services_running = False

        # Check native service state
        self.docling_running = self.docling_manager.is_running()


        # Check for OAuth configuration
        self.has_oauth_config = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

        # Set default button focus
        if self.services_running and self.docling_running:
            self.default_button_id = "open-app-btn"
        elif self.has_oauth_config:
            self.default_button_id = "advanced-setup-btn"
        else:
            self.default_button_id = "basic-setup-btn"

        # Update the welcome text
        try:
            welcome_widget = self.query_one("#welcome-text")
            welcome_widget.update(self._create_welcome_text())
        except:
            pass  # Widget might not be mounted yet

        # Focus the appropriate button (the buttons are created correctly in compose,
        # the issue was they weren't being updated after service operations)
        self.call_after_refresh(self._focus_appropriate_button)

    def _focus_appropriate_button(self) -> None:
        """Focus the appropriate button based on current state."""
        try:
            if self.services_running and self.docling_running:
                self.query_one("#open-app-btn").focus()
            elif self.has_oauth_config:
                self.query_one("#advanced-setup-btn").focus()
            else:
                self.query_one("#basic-setup-btn").focus()
        except:
            pass  # Button might not exist

    async def on_screen_resume(self) -> None:
        """Called when returning from another screen (e.g., config screen)."""
        # Reload environment variables
        load_dotenv(override=True)

        # Update OAuth config state
        self.has_oauth_config = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

        # Re-detect service state
        self._detect_services_sync()

        # Refresh the welcome content and buttons
        await self._refresh_welcome_content()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "basic-setup-btn":
            self.action_no_auth_setup()
        elif event.button.id == "advanced-setup-btn":
            self.action_full_setup()
        elif event.button.id == "status-btn":
            self.action_monitor()
        elif event.button.id == "diagnostics-btn":
            self.action_diagnostics()
        elif event.button.id == "start-all-services-btn":
            self.action_start_all_services()
        elif event.button.id == "stop-all-services-btn":
            self.action_stop_all_services()
        elif event.button.id == "open-app-btn":
            self.action_open_app()

    def action_default_action(self) -> None:
        """Handle Enter key - go to default action based on state."""
        if self.services_running and self.docling_running:
            self.action_open_app()
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

    def action_start_all_services(self) -> None:
        """Start all services (native first, then containers)."""
        self.run_worker(self._start_all_services())

    def action_stop_all_services(self) -> None:
        """Stop all services (containers first, then native)."""
        self.run_worker(self._stop_all_services())

    async def _on_services_operation_complete(self) -> None:
        """Handle completion of services start/stop operation."""
        # Use the same sync detection method that worked on startup
        self._detect_services_sync()

        # Update OAuth config state
        self.has_oauth_config = bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")) or bool(
            os.getenv("MICROSOFT_GRAPH_OAUTH_CLIENT_ID")
        )

        await self._refresh_welcome_content()

    def _update_default_button(self) -> None:
        """Update the default button target based on state."""
        if self.services_running and self.docling_running:
            self.default_button_id = "open-app-btn"
        elif self.has_oauth_config:
            self.default_button_id = "advanced-setup-btn"
        else:
            self.default_button_id = "basic-setup-btn"

    async def _refresh_welcome_content(self) -> None:
        """Refresh welcome text and buttons based on current state."""
        self._update_default_button()

        try:
            welcome_widget = self.query_one("#welcome-text", Static)
            welcome_widget.update(self._create_welcome_text())

            welcome_container = self.query_one("#welcome-container")

            # Remove existing button rows before mounting updated row
            for button_row in list(welcome_container.query(".button-row")):
                await button_row.remove()

            await welcome_container.mount(self._create_dynamic_buttons())
        except Exception:
            # Fallback - just refresh the whole screen
            self.refresh(layout=True)

        self.call_after_refresh(self._focus_appropriate_button)

    async def _start_all_services(self) -> None:
        """Start all services: containers first, then native services."""
        # Step 1: Start container services first (to create the network)
        if self.container_manager.is_available():
            command_generator = self.container_manager.start_services()
            modal = CommandOutputModal(
                "Starting Container Services",
                command_generator,
                on_complete=self._on_containers_started_start_native,
            )
            self.app.push_screen(modal)
        else:
            self.notify("No container runtime available", severity="warning")
            # Still try to start native services
            await self._start_native_services_after_containers()

    async def _on_containers_started_start_native(self) -> None:
        """Called after containers start successfully, now start native services."""
        # Update container state
        self._detect_services_sync()

        # Now start native services (docling-serve can now detect the compose network)
        await self._start_native_services_after_containers()

    async def _start_native_services_after_containers(self) -> None:
        """Start native services after containers have been started."""
        if not self.docling_manager.is_running():
            self.notify("Starting native services...", severity="information")
            success, message = await self.docling_manager.start()
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(f"Failed to start native services: {message}", severity="error")
        else:
            self.notify("Native services already running", severity="information")

        # Update state
        self.docling_running = self.docling_manager.is_running()
        await self._refresh_welcome_content()

    async def _stop_all_services(self) -> None:
        """Stop all services: containers first, then native."""
        # Step 1: Stop container services
        if self.container_manager.is_available() and self.services_running:
            command_generator = self.container_manager.stop_services()
            modal = CommandOutputModal(
                "Stopping Container Services",
                command_generator,
                on_complete=self._on_stop_containers_complete,
            )
            self.app.push_screen(modal)
        else:
            # No containers to stop, go directly to stopping native services
            await self._stop_native_services_after_containers()

    async def _on_stop_containers_complete(self) -> None:
        """Called after containers are stopped, now stop native services."""
        # Update container state
        self._detect_services_sync()

        # Now stop native services
        await self._stop_native_services_after_containers()

    async def _stop_native_services_after_containers(self) -> None:
        """Stop native services after containers have been stopped."""
        if self.docling_manager.is_running():
            self.notify("Stopping native services...", severity="information")
            success, message = await self.docling_manager.stop()
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(f"Failed to stop native services: {message}", severity="error")
        else:
            self.notify("Native services already stopped", severity="information")

        # Update state
        self.docling_running = self.docling_manager.is_running()
        await self._refresh_welcome_content()

    def action_open_app(self) -> None:
        """Open the OpenRAG app in the default browser."""
        import webbrowser
        try:
            webbrowser.open("http://localhost:3000")
            self.notify("Opening OpenRAG app in browser...", severity="information")
        except Exception as e:
            self.notify(f"Error opening app: {e}", severity="error")

    def action_quit(self) -> None:
        """Quit the application."""
        self.app.exit()
