"""Service monitoring screen for OpenRAG TUI."""

import asyncio
import re
from typing import Literal, Any

# Define button variant type
ButtonVariant = Literal["default", "primary", "success", "warning", "error"]

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, DataTable
from textual.timer import Timer
from rich.text import Text
from rich.table import Table

from ..managers.container_manager import ContainerManager, ServiceStatus, ServiceInfo
from ..managers.docling_manager import DoclingManager
from ..utils.platform import RuntimeType
from ..widgets.command_modal import CommandOutputModal
from ..widgets.diagnostics_notification import notify_with_diagnostics


class MonitorScreen(Screen):
    """Service monitoring and control screen."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
        ("s", "start", "Start Services"),
        ("t", "stop", "Stop Services"),
        ("u", "upgrade", "Upgrade"),
        ("x", "reset", "Reset"),
        ("l", "logs", "View Logs"),
        ("j", "cursor_down", "Move Down"),
        ("k", "cursor_up", "Move Up"),
    ]

    def __init__(self):
        super().__init__()
        self.container_manager = ContainerManager()
        self.docling_manager = DoclingManager()
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
        # Just show the services content directly (no header, no tabs)
        yield from self._create_services_tab()

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
        self.images_table = DataTable(id="images-table", show_cursor=False)
        self.images_table.can_focus = False
        self.images_table.add_columns("Image", "Digest")
        yield self.images_table
        yield Static(" ")
        # Dynamic controls container; populated based on running state
        yield Horizontal(id="services-controls", classes="button-row")
        # Create services table with image + digest info
        self.services_table = DataTable(id="services-table")
        self.services_table.add_columns(
            "Service", "Status", "Health", "Ports", "Image", "Digest"
        )
        yield self.services_table

    def _get_runtime_status(self) -> Text:
        """Get container runtime status text."""
        status_text = Text()

        if not self.container_manager.is_available():
            status_text.append(
                "WARNING: No container runtime available\n", style="bold red"
            )
            status_text.append(
                "Please install Docker or Podman to continue.\n", style="dim"
            )
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

    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        await self._refresh_services()
        # Set up auto-refresh every 5 seconds
        self.refresh_timer = self.set_interval(5.0, self._auto_refresh)

        # Focus the services table
        try:
            self.services_table.focus()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        # Stop following logs if running
        self._stop_follow()

    async def on_screen_resume(self) -> None:
        """Called when the screen is resumed (e.g., after a modal is closed)."""
        # Refresh services when returning from a modal
        await self._refresh_services()

    async def _refresh_services(self) -> None:
        """Refresh the services table."""
        if not self.container_manager.is_available():
            return

        services = await self.container_manager.get_service_status(force_refresh=True)
        # Collect images actually reported by running/stopped containers so names match runtime
        images_set = set()
        for svc in services.values():
            img = (svc.image or "").strip()
            if img and img != "N/A":
                images_set.add(img)
        # Ensure compose-declared images are also shown (e.g., langflow when stopped)
        try:
            for img in (
                self.container_manager._parse_compose_images()
            ):  # best-effort, no YAML dep
                if img:
                    images_set.add(img)
        except Exception:
            pass
        images = list(images_set)
        # Lookup digests/IDs for these image names
        digest_map = await self.container_manager.get_images_digests(images)

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
                digest_map.get(service_info.image or "", "-"),
            )
        
        # Add docling serve as a service
        docling_status = self.docling_manager.get_status()
        docling_running = docling_status["status"] == "running"
        docling_status_text = "running" if docling_running else "stopped"
        docling_style = "bold green" if docling_running else "bold red"
        docling_port = f"{docling_status['host']}:{docling_status['port']}" if docling_running else "N/A"
        
        self.services_table.add_row(
            "docling-serve",
            Text(docling_status_text, style=docling_style),
            "N/A",
            docling_port,
            "docling-serve (in-process)",
            "N/A",
        )
        # Populate images table (unique images as reported by runtime)
        if self.images_table:
            for image in sorted(images):
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
            ServiceStatus.UNKNOWN: "dim",
        }
        return status_styles.get(status, "white")

    async def _auto_refresh(self) -> None:
        """Auto-refresh services if not in operation."""
        if not self.operation_in_progress:
            await self._refresh_services()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id or ""
        button_label = event.button.label or ""

        # Use button ID prefixes to determine action, ignoring any random suffix
        if button_id.startswith("start-btn"):
            self.run_worker(self._start_services())
        elif button_id.startswith("stop-btn"):
            self.run_worker(self._stop_services())
        elif button_id.startswith("restart-btn"):
            self.run_worker(self._restart_services())
        elif button_id.startswith("upgrade-btn"):
            self.run_worker(self._upgrade_services())
        elif button_id.startswith("reset-btn"):
            self.run_worker(self._reset_services())
        elif button_id.startswith("docling-start-btn"):
            self.run_worker(self._start_docling_serve())
        elif button_id.startswith("docling-stop-btn"):
            self.run_worker(self._stop_docling_serve())
        elif button_id == "toggle-mode-btn":
            self.action_toggle_mode()
        elif button_id.startswith("refresh-btn"):
            self.action_refresh()
        elif button_id.startswith("back-btn"):
            self.action_back()
        elif button_id.startswith("logs-"):
            # Map button IDs to actual service names
            service_mapping = {
                "logs-backend": "openrag-backend",
                "logs-frontend": "openrag-frontend",
                "logs-opensearch": "opensearch",
                "logs-langflow": "langflow",
            }

            # Extract the base button ID (without any suffix)
            button_base_id = button_id.split("-")[0] + "-" + button_id.split("-")[1]

            service_name = service_mapping.get(button_base_id)
            if service_name:
                # Load recent logs then start following
                self.run_worker(self._show_logs(service_name))
                self._start_follow(service_name)

    async def _start_services(self, cpu_mode: bool = False) -> None:
        """Start services with progress updates."""
        self.operation_in_progress = True
        try:
            # Show command output in modal dialog
            command_generator = self.container_manager.start_services(cpu_mode)
            modal = CommandOutputModal(
                "Starting Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _stop_services(self) -> None:
        """Stop services with progress updates."""
        self.operation_in_progress = True
        try:
            # Show command output in modal dialog
            command_generator = self.container_manager.stop_services()
            modal = CommandOutputModal(
                "Stopping Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _restart_services(self) -> None:
        """Restart services with progress updates."""
        self.operation_in_progress = True
        try:
            # Show command output in modal dialog
            command_generator = self.container_manager.restart_services()
            modal = CommandOutputModal(
                "Restarting Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _upgrade_services(self) -> None:
        """Upgrade services with progress updates."""
        self.operation_in_progress = True
        try:
            # Show command output in modal dialog
            command_generator = self.container_manager.upgrade_services()
            modal = CommandOutputModal(
                "Upgrading Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _reset_services(self) -> None:
        """Reset services with progress updates."""
        self.operation_in_progress = True
        try:
            # Show command output in modal dialog
            command_generator = self.container_manager.reset_services()
            modal = CommandOutputModal(
                "Resetting Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _start_docling_serve(self) -> None:
        """Start docling serve."""
        self.operation_in_progress = True
        try:
            success, message = await self.docling_manager.start()
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(f"Failed to start docling serve: {message}", severity="error")
            # Refresh the services table to show updated status
            await self._refresh_services()
        except Exception as e:
            self.notify(f"Error starting docling serve: {str(e)}", severity="error")
        finally:
            self.operation_in_progress = False

    async def _stop_docling_serve(self) -> None:
        """Stop docling serve."""
        self.operation_in_progress = True
        try:
            success, message = await self.docling_manager.stop()
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(f"Failed to stop docling serve: {message}", severity="error")
            # Refresh the services table to show updated status
            await self._refresh_services()
        except Exception as e:
            self.notify(f"Error stopping docling serve: {str(e)}", severity="error")
        finally:
            self.operation_in_progress = False

    def _strip_ansi_codes(self, text: str) -> str:
        """Strip ANSI escape sequences from text."""
        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text)

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
                # Only use scroll_end which is the correct method
                scroller.scroll_end(animate=False)
            except Exception:
                pass
        else:
            notify_with_diagnostics(
                self.app,
                f"Failed to get logs for {service_name}: {logs}",
                severity="error",
            )

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
                    # Only use scroll_end which is the correct method
                    scroller.scroll_end(animate=False)
                except Exception:
                    pass
        except Exception as e:
            notify_with_diagnostics(
                self.app, f"Error following logs: {e}", severity="error"
            )

    def action_refresh(self) -> None:
        """Refresh services manually."""
        self.run_worker(self._refresh_services())

    def action_cursor_down(self) -> None:
        """Move cursor down in services table."""
        try:
            self.services_table.action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Move cursor up in services table."""
        try:
            self.services_table.action_cursor_up()
        except Exception:
            pass

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
            self.notify(
                "Switched to GPU compose" if not current else "Switched to CPU compose",
                severity="information",
            )
            self._update_mode_row()
            self.action_refresh()
        except Exception as e:
            notify_with_diagnostics(
                self.app, f"Failed to toggle mode: {e}", severity="error"
            )

    def _update_controls(self, services: list[ServiceInfo]) -> None:
        """Update control buttons based on running state."""
        try:
            # Get the controls container
            controls = self.query_one("#services-controls", Horizontal)

            # Check if any services are running
            any_running = any(s.status == ServiceStatus.RUNNING for s in services)

            # Clear existing buttons by removing all children
            controls.remove_children()

            # Use a single ID for each button type, but make them unique with a suffix
            # This ensures we don't create duplicate IDs across refreshes
            import random

            suffix = f"-{random.randint(10000, 99999)}"

            # Add appropriate buttons based on service state
            if any_running:
                # When services are running, show stop and restart
                controls.mount(
                    Button("Stop Services", variant="error", id=f"stop-btn{suffix}")
                )
                controls.mount(
                    Button("Restart", variant="primary", id=f"restart-btn{suffix}")
                )
            else:
                # When services are not running, show start
                controls.mount(
                    Button("Start Services", variant="success", id=f"start-btn{suffix}")
                )

            # Always show upgrade and reset buttons
            controls.mount(
                Button("Upgrade", variant="warning", id=f"upgrade-btn{suffix}")
            )
            controls.mount(Button("Reset", variant="error", id=f"reset-btn{suffix}"))
            
            # Add docling serve controls
            docling_running = self.docling_manager.is_running()
            if docling_running:
                controls.mount(
                    Button("Stop Docling", variant="error", id=f"docling-stop-btn{suffix}")
                )
            else:
                controls.mount(
                    Button("Start Docling", variant="success", id=f"docling-start-btn{suffix}")
                )

        except Exception as e:
            notify_with_diagnostics(
                self.app, f"Error updating controls: {e}", severity="error"
            )

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

    def action_logs(self) -> None:
        """View logs for the selected service."""
        try:
            # Get the currently focused row in the services table
            table = self.query_one("#services-table", DataTable)

            if table.cursor_row is not None and table.cursor_row >= 0:
                # Get the service name from the first column of the selected row
                row_data = table.get_row_at(table.cursor_row)
                if row_data:
                    service_name = str(row_data[0])  # First column is service name

                    # Map display names to actual service names
                    service_mapping = {
                        "openrag-backend": "openrag-backend",
                        "openrag-frontend": "openrag-frontend",
                        "opensearch": "opensearch",
                        "langflow": "langflow",
                        "dashboards": "dashboards",
                        "docling-serve": "docling-serve",  # Add docling-serve mapping
                    }

                    actual_service_name = service_mapping.get(
                        service_name, service_name
                    )

                    # Push the logs screen with the selected service
                    from .logs import LogsScreen

                    logs_screen = LogsScreen(initial_service=actual_service_name)
                    self.app.push_screen(logs_screen)
                else:
                    self.notify("No service selected", severity="warning")
            else:
                self.notify("No service selected", severity="warning")
        except Exception as e:
            self.notify(f"Error opening logs: {e}", severity="error")
