"""Service monitoring screen for OpenRAG TUI."""

import asyncio
import re
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable, TabbedContent, TabPane
from textual.timer import Timer
from rich.text import Text
from rich.table import Table

from ..managers.container_manager import ContainerManager, ServiceStatus, ServiceInfo
from ..utils.platform import RuntimeType


class MonitorScreen(Screen):
    """Service monitoring and control screen."""
    
    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
        ("s", "start", "Start Services"),
        ("t", "stop", "Stop Services"),
        ("u", "upgrade", "Upgrade"),
        ("x", "reset", "Reset"),
    ]
    
    def __init__(self):
        super().__init__()
        self.container_manager = ContainerManager()
        self.services_table = None
        self.images_table = None
        self.status_text = None
        self.refresh_timer = None
        self.operation_in_progress = False
        self._follow_task = None
        self._follow_service = None
        self._logs_buffer = []
    
    def compose(self) -> ComposeResult:
        """Create the monitoring screen layout."""
        yield Header()
        
        with TabbedContent(id="monitor-tabs"):
            with TabPane("Services", id="services-tab"):
                yield from self._create_services_tab()
            with TabPane("Logs", id="logs-tab"):
                yield from self._create_logs_tab()
            with TabPane("System", id="system-tab"):
                yield from self._create_system_tab()
        
        yield Footer()
    
    def _create_services_tab(self) -> ComposeResult:
        """Create the services monitoring tab."""
        # Current mode indicator + toggle
        yield Horizontal(
            Static("", id="mode-indicator"),
            Button("Toggle Mode", id="toggle-mode-btn"),
            classes="button-row",
            id="mode-row",
        )
        # Images summary table (above services)
        yield Static("Container Images", classes="tab-header")
        self.images_table = DataTable(id="images-table")
        self.images_table.add_columns("Image", "Digest")
        yield self.images_table
        yield Static(" ")
        # Dynamic controls container; populated based on running state
        yield Horizontal(id="services-controls", classes="button-row")
        # Create services table with image + digest info
        self.services_table = DataTable(id="services-table")
        self.services_table.add_columns("Service", "Status", "Health", "Ports", "Image", "Digest")
        yield self.services_table
        yield Horizontal(
            Button("Refresh", variant="default", id="refresh-btn"),
            Button("Back", variant="default", id="back-btn"),
            classes="button-row"
        )
    
    def _create_logs_tab(self) -> ComposeResult:
        """Create the logs viewing tab."""
        logs_content = Static("Select a service to view logs", id="logs-content", markup=False)

        yield Static("Service Logs", id="logs-header")
        yield Horizontal(
            Button("Backend", variant="default", id="logs-backend"),
            Button("Frontend", variant="default", id="logs-frontend"),
            Button("OpenSearch", variant="default", id="logs-opensearch"),
            Button("Langflow", variant="default", id="logs-langflow"),
            classes="button-row"
        )
        yield ScrollableContainer(logs_content, id="logs-scroll")
    
    def _create_system_tab(self) -> ComposeResult:
        """Create the system information tab."""
        system_info = Static(self._get_system_info(), id="system-info")
        
        yield Static("System Information", id="system-header")
        yield system_info
    
    def _get_runtime_status(self) -> Text:
        """Get container runtime status text."""
        status_text = Text()
        
        if not self.container_manager.is_available():
            status_text.append("WARNING: No container runtime available\n", style="bold red")
            status_text.append("Please install Docker or Podman to continue.\n", style="dim")
            return status_text
        
        runtime_info = self.container_manager.get_runtime_info()
        
        if runtime_info.runtime_type == RuntimeType.DOCKER:
            status_text.append("Docker Runtime\n", style="bold blue")
        elif runtime_info.runtime_type == RuntimeType.PODMAN:
            status_text.append("Podman Runtime\n", style="bold purple")
        else:
            status_text.append("Container Runtime\n", style="bold green")
        
        if runtime_info.version:
            status_text.append(f"Version: {runtime_info.version}\n", style="dim")
        
        # Check Podman macOS memory if applicable
        if runtime_info.runtime_type == RuntimeType.PODMAN:
            is_sufficient, message = self.container_manager.check_podman_macos_memory()
            if not is_sufficient:
                status_text.append(f"WARNING: {message}\n", style="bold yellow")
        
        return status_text
    
    def _get_system_info(self) -> Text:
        """Get system information text."""
        info_text = Text()
        
        runtime_info = self.container_manager.get_runtime_info()
        
        info_text.append("Container Runtime Information\n", style="bold")
        info_text.append("=" * 30 + "\n")
        info_text.append(f"Type: {runtime_info.runtime_type.value}\n")
        info_text.append(f"Compose Command: {' '.join(runtime_info.compose_command)}\n")
        info_text.append(f"Runtime Command: {' '.join(runtime_info.runtime_command)}\n")
        
        if runtime_info.version:
            info_text.append(f"Version: {runtime_info.version}\n")
        # Removed compose files section for cleaner display

        return info_text
    
    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        await self._refresh_services()
        # Set up auto-refresh every 5 seconds
        self.refresh_timer = self.set_interval(5.0, self._auto_refresh)
    
    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        # Stop following logs if running
        self._stop_follow()
    
    async def _refresh_services(self) -> None:
        """Refresh the services table."""
        if not self.container_manager.is_available():
            return
        
        services = await self.container_manager.get_service_status(force_refresh=True)
        # Fetch image info independent of service state
        project_images = await self.container_manager.get_project_images_info()
        digest_map = {img: dig for img, dig in project_images}
        images = [img for img, _ in project_images]
        
        # Clear existing rows
        self.services_table.clear()
        if self.images_table:
            self.images_table.clear()
        
        # Add service rows
        for service_name, service_info in services.items():
            status_style = self._get_status_style(service_info.status)
            
            self.services_table.add_row(
                service_info.name,
                Text(service_info.status.value, style=status_style),
                service_info.health or "N/A",
                ", ".join(service_info.ports) if service_info.ports else "N/A",
                service_info.image or "N/A",
                digest_map.get(service_info.image or "", "-")
            )
        # Populate images table (unique images)
        if self.images_table:
            seen=set()
            for image in images:
                if not image or image in seen:
                    continue
                seen.add(image)
                self.images_table.add_row(image, digest_map.get(image, "-"))
        # Update controls based on overall state
        self._update_controls(list(services.values()))
        # Update mode indicator
        self._update_mode_row()
    
    def _get_status_style(self, status: ServiceStatus) -> str:
        """Get the Rich style for a service status."""
        status_styles = {
            ServiceStatus.RUNNING: "bold green",
            ServiceStatus.STOPPED: "bold red",
            ServiceStatus.STARTING: "bold yellow",
            ServiceStatus.STOPPING: "bold yellow",
            ServiceStatus.ERROR: "bold red",
            ServiceStatus.MISSING: "dim",
            ServiceStatus.UNKNOWN: "dim"
        }
        return status_styles.get(status, "white")
    
    async def _auto_refresh(self) -> None:
        """Auto-refresh services if not in operation."""
        if not self.operation_in_progress:
            await self._refresh_services()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "start-btn":
            self.run_worker(self._start_services())
        elif event.button.id == "stop-btn":
            self.run_worker(self._stop_services())
        elif event.button.id == "restart-btn":
            self.run_worker(self._restart_services())
        elif event.button.id == "upgrade-btn":
            self.run_worker(self._upgrade_services())
        elif event.button.id == "reset-btn":
            self.run_worker(self._reset_services())
        elif event.button.id == "toggle-mode-btn":
            self.action_toggle_mode()
        elif event.button.id == "refresh-btn":
            self.action_refresh()
        elif event.button.id == "back-btn":
            self.action_back()
        elif event.button.id.startswith("logs-"):
            # Map button IDs to actual service names
            service_mapping = {
                "logs-backend": "openrag-backend",
                "logs-frontend": "openrag-frontend", 
                "logs-opensearch": "opensearch",
                "logs-langflow": "langflow"
            }
            service_name = service_mapping.get(event.button.id)
            if service_name:
                # Load recent logs then start following
                self.run_worker(self._show_logs(service_name))
                self._start_follow(service_name)
    
    async def _start_services(self, cpu_mode: bool = False) -> None:
        """Start services with progress updates."""
        self.operation_in_progress = True
        try:
            async for is_complete, message in self.container_manager.start_services(cpu_mode):
                self.notify(message, severity="success" if is_complete else "info")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False
    
    async def _stop_services(self) -> None:
        """Stop services with progress updates."""
        self.operation_in_progress = True
        try:
            async for is_complete, message in self.container_manager.stop_services():
                self.notify(message, severity="success" if is_complete else "info")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False
    
    async def _restart_services(self) -> None:
        """Restart services with progress updates."""
        self.operation_in_progress = True
        try:
            async for is_complete, message in self.container_manager.restart_services():
                self.notify(message, severity="success" if is_complete else "info")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False
    
    async def _upgrade_services(self) -> None:
        """Upgrade services with progress updates."""
        self.operation_in_progress = True
        try:
            async for is_complete, message in self.container_manager.upgrade_services():
                self.notify(message, severity="success" if is_complete else "warning")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False
    
    async def _reset_services(self) -> None:
        """Reset services with progress updates."""
        self.operation_in_progress = True
        try:
            async for is_complete, message in self.container_manager.reset_services():
                self.notify(message, severity="success" if is_complete else "warning")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False
    
    def _strip_ansi_codes(self, text: str) -> str:
        """Strip ANSI escape sequences from text."""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)
    
    async def _show_logs(self, service_name: str) -> None:
        """Show logs for a service."""
        success, logs = await self.container_manager.get_service_logs(service_name)

        if success:
            # Strip ANSI codes and limit length to prevent UI issues
            cleaned_logs = self._strip_ansi_codes(logs)
            # Limit to last 5000 characters to prevent performance issues
            if len(cleaned_logs) > 5000:
                cleaned_logs = "...\n" + cleaned_logs[-5000:]

            logs_widget = self.query_one("#logs-content", Static)
            logs_widget.update(cleaned_logs)
            # Reset buffer to the current content split by lines (cap buffer)
            self._logs_buffer = cleaned_logs.splitlines()[-1000:]
            # Try to scroll to end of container
            try:
                scroller = self.query_one("#logs-scroll", ScrollableContainer)
                if hasattr(scroller, "scroll_end"):
                    scroller.scroll_end(animate=False)
                elif hasattr(scroller, "scroll_to_end"):
                    scroller.scroll_to_end()
            except Exception:
                pass
        else:
            self.notify(f"Failed to get logs for {service_name}: {logs}", severity="error")

    def _stop_follow(self) -> None:
        task = self._follow_task
        if task and hasattr(task, "cancel"):
            try:
                task.cancel()
            except Exception:
                pass
        self._follow_task = None
        self._follow_service = None

    def _start_follow(self, service_name: str) -> None:
        # Stop any existing follower and start a new one
        self._stop_follow()
        self._follow_service = service_name
        self._follow_task = self.run_worker(self._follow_logs(), exclusive=False)

    async def _follow_logs(self) -> None:
        """Follow logs for the currently selected service and append to the view."""
        service_name = self._follow_service
        if not service_name:
            return
        if not self.container_manager.is_available():
            return
        try:
            async for line in self.container_manager.follow_service_logs(service_name):
                cleaned = self._strip_ansi_codes(line.rstrip("\n"))
                if not cleaned:
                    continue
                self._logs_buffer.append(cleaned)
                # Keep only the last 1000 lines to avoid growth
                if len(self._logs_buffer) > 1000:
                    self._logs_buffer = self._logs_buffer[-1000:]
                try:
                    logs_widget = self.query_one("#logs-content", Static)
                    logs_widget.update("\n".join(self._logs_buffer))
                    scroller = self.query_one("#logs-scroll", ScrollableContainer)
                    if hasattr(scroller, "scroll_end"):
                        scroller.scroll_end(animate=False)
                except Exception:
                    pass
        except Exception as e:
            self.notify(f"Error following logs: {e}", severity="error")
    
    def action_refresh(self) -> None:
        """Refresh services manually."""
        self.run_worker(self._refresh_services())

    def _update_mode_row(self) -> None:
        """Update the mode indicator and toggle button label."""
        try:
            use_cpu = getattr(self.container_manager, "use_cpu_compose", True)
            indicator = self.query_one("#mode-indicator", Static)
            mode_text = "Mode: CPU (no GPU detected)" if use_cpu else "Mode: GPU"
            indicator.update(mode_text)
            toggle_btn = self.query_one("#toggle-mode-btn", Button)
            toggle_btn.label = "Switch to GPU Mode" if use_cpu else "Switch to CPU Mode"
        except Exception:
            pass

    def action_toggle_mode(self) -> None:
        """Toggle between CPU/GPU compose files and refresh view."""
        try:
            current = getattr(self.container_manager, "use_cpu_compose", True)
            self.container_manager.use_cpu_compose = not current
            self.notify("Switched to GPU compose" if not current else "Switched to CPU compose", severity="info")
            self._update_mode_row()
            self.action_refresh()
        except Exception as e:
            self.notify(f"Failed to toggle mode: {e}", severity="error")

    def _update_controls(self, services: list[ServiceInfo]) -> None:
        """Render control buttons based on running state and set default focus."""
        try:
            controls = self.query_one("#services-controls", Horizontal)
            controls.remove_children()
            any_running = any(s.status == ServiceStatus.RUNNING for s in services)
            if any_running:
                controls.mount(Button("Stop Services", variant="error", id="stop-btn"))
                controls.mount(Button("Restart", variant="primary", id="restart-btn"))
                controls.mount(Button("Upgrade", variant="warning", id="upgrade-btn"))
                controls.mount(Button("Reset", variant="error", id="reset-btn"))
                # Focus Stop by default when running
                try:
                    self.query_one("#stop-btn", Button).focus()
                except Exception:
                    pass
            else:
                controls.mount(Button("Start Services", variant="success", id="start-btn"))
                try:
                    self.query_one("#start-btn", Button).focus()
                except Exception:
                    pass
        except Exception:
            pass
    
    def action_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()
    
    def action_start(self) -> None:
        """Start services."""
        self.run_worker(self._start_services())
    
    def action_stop(self) -> None:
        """Stop services."""
        self.run_worker(self._stop_services())
    
    def action_upgrade(self) -> None:
        """Upgrade services."""
        self.run_worker(self._upgrade_services())
    
    def action_reset(self) -> None:
        """Reset services."""
        self.run_worker(self._reset_services())
