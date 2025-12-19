"""Service monitoring screen for OpenRAG TUI."""

import asyncio
import re
import shutil
from pathlib import Path
from typing import Literal, Any, Optional, AsyncIterator

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
from ..widgets.flow_backup_warning_modal import FlowBackupWarningModal
from ..widgets.factory_reset_warning_modal import FactoryResetWarningModal
from ..widgets.version_mismatch_warning_modal import VersionMismatchWarningModal
from ..widgets.upgrade_instructions_modal import UpgradeInstructionsModal
from ..widgets.diagnostics_notification import notify_with_diagnostics


class MonitorScreen(Screen):
    """Service monitoring and control screen."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
        ("s", "start", "Start Services"),
        ("t", "stop", "Stop Services"),
        ("u", "upgrade", "Upgrade"),
        ("x", "reset", "Factory Reset"),
        ("l", "logs", "View Logs"),
        ("g", "toggle_mode", "Toggle GPU/CPU"),
        ("j", "cursor_down", "Move Down"),
        ("k", "cursor_up", "Move Up"),
    ]

    def __init__(self):
        super().__init__()
        self._container_manager = None  # Use app's shared instance
        self.docling_manager = DoclingManager()
        self.services_table = None
        self.docling_table = None
        self.images_table = None
        self.status_text = None
        self.refresh_timer = None
        self.operation_in_progress = False
        self._follow_task = None

        # Track which table was last selected for mutual exclusion
        self._last_selected_table = None

    @property
    def container_manager(self) -> ContainerManager:
        """Get the shared container manager from the app."""
        if self._container_manager is None:
            self._container_manager = self.app.container_manager
        return self._container_manager


    def compose(self) -> ComposeResult:
        """Create the monitoring screen layout."""
        # Just show the services content directly (no header, no tabs)
        yield from self._create_services_tab()

        yield Footer()

    def _create_services_tab(self) -> ComposeResult:
        """Create the services monitoring tab."""
        # GPU/CPU mode section
        yield Static("GPU Mode", id="mode-indicator", classes="tab-header")
        yield Horizontal(
            Button("Switch to CPU Mode", id="toggle-mode-btn"),
            classes="button-row",
            id="mode-row",
        )

        # Container Images table
        yield Static("Container Images", classes="tab-header")
        self.images_table = DataTable(id="images-table", show_cursor=False)
        self.images_table.can_focus = False
        self.images_table.add_columns("Image", "Digest")
        yield self.images_table
        yield Static(" ")

        # Container Services table
        yield Static("Container Services", classes="tab-header")
        # Dynamic controls container; populated based on running state
        yield Horizontal(id="services-controls", classes="button-row")
        # Create services table with image + digest info
        self.services_table = DataTable(id="services-table")
        self.services_table.add_columns(
            "Service", "Status", "Health", "Ports", "Image", "Digest"
        )
        yield self.services_table
        yield Static(" ")

        # Docling Services table
        yield Static("Native Services", classes="tab-header")
        # Dynamic controls for docling service
        yield Horizontal(id="docling-controls", classes="button-row")
        # Create docling table with relevant columns only
        self.docling_table = DataTable(id="docling-table")
        self.docling_table.add_columns("Service", "Status", "Port", "PID", "Actions")
        yield self.docling_table

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

        self._focus_services_table()

    def on_unmount(self) -> None:
        """Clean up when unmounting."""
        if self.refresh_timer:
            self.refresh_timer.stop()
        # Stop following logs if running
        self._stop_follow()
        # Clean up docling manager
        if hasattr(self, "docling_manager"):
            self.docling_manager.cleanup()
        # Reset follow state (already done in _stop_follow, but ensure clean state)
        self._follow_service = None
        self._logs_buffer = []

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
        if self.docling_table:
            self.docling_table.clear()
        if self.images_table:
            self.images_table.clear()

        # Add container service rows
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

        # Add docling serve to its own table
        docling_status = self.docling_manager.get_status()
        docling_status_value = docling_status["status"]
        docling_running = docling_status_value == "running"
        docling_starting = docling_status_value == "starting"

        if docling_running:
            docling_status_text = "running"
            docling_style = "bold green"
        elif docling_starting:
            docling_status_text = "starting"
            docling_style = "bold yellow"
        else:
            docling_status_text = "stopped"
            docling_style = "bold red"

        docling_port = (
            f"{docling_status['host']}:{docling_status['port']}"
            if (docling_running or docling_starting)
            else "N/A"
        )
        docling_pid = (
            str(docling_status.get("pid")) if docling_status.get("pid") else "N/A"
        )

        if self.docling_table:
            self.docling_table.add_row(
                "docling-serve",
                Text(docling_status_text, style=docling_style),
                docling_port,
                docling_pid,
                "Start/Stop/Logs",
            )
            # Restore docling selection when it was the last active table
            if self._last_selected_table == "docling":
                self._focus_docling_table(focus=False, set_last=False)
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
        elif button_id.startswith("docling-restart-btn"):
            self.run_worker(self._restart_docling_serve())
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

    async def _start_services(self, cpu_mode: Optional[bool] = None) -> None:
        """Start services with progress updates."""
        self.operation_in_progress = True
        try:
            # Check for port conflicts before attempting to start
            (
                ports_available,
                conflicts,
            ) = await self.container_manager.check_ports_available()
            if not ports_available:
                # Show error notification instead of modal
                conflict_msgs = []
                for service_name, port, error_msg in conflicts[:3]:  # Show first 3
                    conflict_msgs.append(f"{service_name} (port {port})")

                conflict_str = ", ".join(conflict_msgs)
                if len(conflicts) > 3:
                    conflict_str += f" and {len(conflicts) - 3} more"

                self.notify(
                    f"Cannot start services: Port conflicts detected for {conflict_str}. "
                    f"Please stop the conflicting services first.",
                    severity="error",
                    timeout=10,
                )
                # Refresh to show current state
                await self._refresh_services()
                return

            # Check for version mismatch
            (
                has_mismatch,
                container_version,
                tui_version,
            ) = await self.container_manager.check_version_mismatch()
            if has_mismatch and container_version:
                # Show warning modal and wait for user decision
                should_continue = await self.app.push_screen_wait(
                    VersionMismatchWarningModal(container_version, tui_version)
                )
                if not should_continue:
                    self.notify("Start cancelled", severity="information")
                    return
                # Ensure OPENRAG_VERSION is set in .env BEFORE starting services
                # This ensures docker compose reads the correct version
                try:
                    from ..managers.env_manager import EnvManager
                    env_manager = EnvManager()
                    env_manager.ensure_openrag_version()
                    # Small delay to ensure .env file is written and flushed
                    await asyncio.sleep(0.5)
                except Exception:
                    pass  # Continue even if version setting fails

            # Show command output in modal dialog
            command_generator = self.container_manager.start_services(cpu_mode)
            modal = CommandOutputModal(
                "Starting Services",
                command_generator,
                on_complete=self._on_start_complete,  # Refresh after completion
            )
            self.app.push_screen(modal)
        except Exception as e:
            self.notify(f"Error starting services: {str(e)}", severity="error")
            await self._refresh_services()
        finally:
            self.operation_in_progress = False

    async def _on_start_complete(self) -> None:
        """Callback after service start completes."""
        await self._refresh_services()

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
        """Check TUI version and show upgrade instructions."""
        self.operation_in_progress = True
        try:
            from ..utils.version_check import check_if_latest

            # Check if current version is latest
            is_latest, latest_version, current_version = await check_if_latest()

            if is_latest:
                # Show "this is the latest version" toast
                self.notify(
                    f"You are running the latest version ({current_version}).",
                    severity="success",
                    timeout=5,
                )
            else:
                # Show upgrade instructions in a modal dialog
                await self.app.push_screen_wait(
                    UpgradeInstructionsModal(current_version, latest_version)
                )
        except Exception as e:
            self.notify(
                f"Error checking version: {str(e)}", severity="error", timeout=10
            )
        finally:
            self.operation_in_progress = False

    async def _reset_services(self) -> None:
        """Factory reset: clear config and opensearch-data, then reset services."""
        self.operation_in_progress = True
        try:
            # Show factory reset warning modal first
            should_continue = await self.app.push_screen_wait(
                FactoryResetWarningModal()
            )
            if not should_continue:
                self.notify("Factory reset cancelled", severity="information")
                return

            # Check for flow backups before resetting
            delete_backups = False
            if self._check_flow_backups():
                # Show warning modal and wait for user decision
                should_continue, delete_backups = await self.app.push_screen_wait(
                    FlowBackupWarningModal(operation="reset")
                )
                if not should_continue:
                    self.notify("Factory reset cancelled", severity="information")
                    return

            # Clear config, conversations.json, and optionally flow backups (before stopping containers)
            try:
                # Get paths from env config
                from ..managers.env_manager import EnvManager
                env_manager = EnvManager()
                env_manager.load_existing_env()

                def expand_path(path_str: str) -> Path:
                    return Path(path_str.replace("$HOME", str(Path.home()))).expanduser()

                config_path = expand_path(env_manager.config.openrag_config_path)
                flows_path = expand_path(env_manager.config.openrag_flows_path)
                flows_backup_path = flows_path / "backup"

                if config_path.exists():
                    # Use container to handle files owned by container user
                    success, msg = await self.container_manager.clear_directory_with_container(config_path)
                    if not success:
                        # Fallback to regular rmtree if container method fails
                        shutil.rmtree(config_path)
                    # Recreate empty config directory
                    config_path.mkdir(parents=True, exist_ok=True)

                # Also delete legacy TUI config folder if it exists (~/.openrag/tui/config/)
                tui_config_path = expand_path(env_manager.config.openrag_tui_config_path_legacy)
                if tui_config_path.exists():
                    success, msg = await self.container_manager.clear_directory_with_container(tui_config_path)
                    if not success:
                        # Fallback to regular rmtree if container method fails
                        shutil.rmtree(tui_config_path)
                    # Recreate empty config directory
                    tui_config_path.mkdir(parents=True, exist_ok=True)

                # Delete flow backups only if user chose to (and they actually exist)
                if self._check_flow_backups():
                    if delete_backups:
                        # Use container to handle files owned by container user
                        success, msg = await self.container_manager.clear_directory_with_container(flows_backup_path)
                        if not success:
                            # Fallback to regular rmtree if container method fails
                            shutil.rmtree(flows_backup_path)
                        # Recreate empty backup directory
                        flows_backup_path.mkdir(parents=True, exist_ok=True)
                        self.notify("Flow backups deleted", severity="information")
                    else:
                        self.notify(f"Flow backups preserved in {flows_backup_path}", severity="information")
                
            except Exception as e:
                self.notify(
                    f"Error clearing config: {str(e)}",
                    severity="error",
                )
                return

            # Show command output in modal dialog for stopping services and clearing data
            command_generator = self._factory_reset_with_data_clear()
            modal = CommandOutputModal(
                "Factory Resetting Services",
                command_generator,
                on_complete=None,  # We'll refresh in on_screen_resume instead
            )
            self.app.push_screen(modal)
        finally:
            self.operation_in_progress = False

    async def _factory_reset_with_data_clear(self) -> AsyncIterator[tuple[bool, str]]:
        """Generator that stops services and clears opensearch data."""
        # First stop all services
        async for success, message in self.container_manager.reset_services():
            yield success, message
            if not success and "failed" in message.lower():
                return
        
        # Now clear opensearch-data using container
        yield False, "Clearing OpenSearch data..."
        # Get opensearch data path from env config
        from ..managers.env_manager import EnvManager
        env_manager = EnvManager()
        env_manager.load_existing_env()
        opensearch_data_path = Path(env_manager.config.opensearch_data_path.replace("$HOME", str(Path.home()))).expanduser()
        if opensearch_data_path.exists():
            async for success, message in self.container_manager.clear_opensearch_data_volume():
                yield success, message
                if not success and "failed" in message.lower():
                    return
            
            # Recreate empty opensearch-data directory
            try:
                opensearch_data_path.mkdir(parents=True, exist_ok=True)
                yield True, "OpenSearch data directory recreated"
            except Exception as e:
                yield False, f"Error recreating opensearch-data directory: {e}"
                return
        
        yield True, "Factory reset completed successfully"

    def _check_flow_backups(self) -> bool:
        """Check if there are any flow backups in flows/backup directory."""
        from pathlib import Path
        from ..managers.env_manager import EnvManager

        # Get flows path from env config
        env_manager = EnvManager()
        env_manager.load_existing_env()
        flows_path = Path(env_manager.config.openrag_flows_path.replace("$HOME", str(Path.home()))).expanduser()
        backup_dir = flows_path / "backup"
        if not backup_dir.exists():
            return False

        try:
            # Check if there are any .json files in the backup directory
            backup_files = list(backup_dir.glob("*.json"))
            return len(backup_files) > 0
        except Exception:
            return False

    async def _start_docling_serve(self) -> None:
        """Start docling serve."""
        self.operation_in_progress = True
        try:
            # Check for port conflicts before attempting to start
            port_available, error_msg = self.docling_manager.check_port_available()
            if not port_available:
                self.notify(
                    f"Cannot start docling serve: {error_msg}. "
                    f"Please stop the conflicting service first.",
                    severity="error",
                    timeout=10,
                )
                # Refresh to show current state
                await self._refresh_services()
                return

            # Start the service (this sets _starting = True internally at the start)
            # Create task and let it begin executing (which sets the flag)
            start_task = asyncio.create_task(self.docling_manager.start())
            # Give it a tiny moment to set the _starting flag
            await asyncio.sleep(0.1)
            # Refresh immediately to show "Starting" status
            await self._refresh_services()
            # Now wait for start to complete
            success, message = await start_task
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(
                    f"Failed to start docling serve: {message}", severity="error"
                )
            # Refresh again to show final status (running or stopped)
            await self._refresh_services()
        except Exception as e:
            self.notify(f"Error starting docling serve: {str(e)}", severity="error")
            # Refresh on error to clear starting status
            await self._refresh_services()
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
                self.notify(
                    f"Failed to stop docling serve: {message}", severity="error"
                )
            # Refresh the services table to show updated status
            await self._refresh_services()
        except Exception as e:
            self.notify(f"Error stopping docling serve: {str(e)}", severity="error")
        finally:
            self.operation_in_progress = False

    async def _restart_docling_serve(self) -> None:
        """Restart docling serve."""
        self.operation_in_progress = True
        try:
            success, message = await self.docling_manager.restart()
            if success:
                self.notify(message, severity="information")
            else:
                self.notify(
                    f"Failed to restart docling serve: {message}", severity="error"
                )
            # Refresh the services table to show updated status
            await self._refresh_services()
        except Exception as e:
            self.notify(f"Error restarting docling serve: {str(e)}", severity="error")
        finally:
            self.operation_in_progress = False

    def _view_docling_logs(self) -> None:
        """View docling serve logs."""
        from .logs import LogsScreen

        self.app.push_screen(LogsScreen(initial_service="docling-serve"))

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
        """Move selection down, handling both tables."""
        active_table = self._get_active_table_name()

        try:
            if active_table == "docling":
                return  # Nothing to move within docling table

            if not self.services_table:
                return

            row_count = self._table_row_count(self.services_table)
            current = self._get_cursor_row(self.services_table)
            if current is None:
                current = 0

            if current < row_count - 1:
                self.services_table.action_cursor_down()
                self._last_selected_table = "services"
            elif self._table_row_count(self.docling_table):
                self._focus_docling_table()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        """Move selection up, handling both tables."""
        active_table = self._get_active_table_name()

        try:
            if active_table == "docling":
                self._focus_services_table(row="last")
                return

            if not self.services_table:
                return

            current = self._get_cursor_row(self.services_table)
            if current is None:
                current = 0

            if current > 0:
                self.services_table.action_cursor_up()
            else:
                # Already at the top; nothing else to do
                self._set_cursor_row(self.services_table, 0)

            self._last_selected_table = "services"
        except Exception:
            pass

    def _update_mode_row(self) -> None:
        """Update the mode indicator and toggle button label."""
        try:
            use_gpu = getattr(self.container_manager, "use_gpu_compose", False)
            indicator = self.query_one("#mode-indicator", Static)
            indicator.update("GPU Mode" if use_gpu else "CPU Mode")
            toggle_btn = self.query_one("#toggle-mode-btn", Button)
            toggle_btn.label = "Switch to CPU Mode" if use_gpu else "Switch to GPU Mode"
        except Exception:
            pass

    def action_toggle_mode(self) -> None:
        """Toggle between CPU/GPU compose files and refresh view."""
        try:
            current = getattr(self.container_manager, "use_gpu_compose", False)
            self.container_manager.use_gpu_compose = not current
            self.notify(
                "Switched to GPU mode" if not current else "Switched to CPU mode",
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
            controls.mount(Button("Factory Reset", variant="error", id=f"reset-btn{suffix}"))

        except Exception as e:
            notify_with_diagnostics(
                self.app, f"Error updating controls: {e}", severity="error"
            )

        # Update docling controls separately
        self._update_docling_controls()

    def _update_docling_controls(self) -> None:
        """Update docling control buttons."""
        try:
            # Get the docling controls container
            docling_controls = self.query_one("#docling-controls", Horizontal)

            # Clear existing buttons
            docling_controls.remove_children()

            # Use a random suffix for unique IDs
            import random

            suffix = f"-{random.randint(10000, 99999)}"

            # Add docling serve controls
            docling_status = self.docling_manager.get_status()
            docling_status_value = docling_status["status"]
            docling_running = docling_status_value == "running"
            docling_starting = docling_status_value == "starting"

            if docling_running:
                docling_controls.mount(
                    Button("Stop", variant="error", id=f"docling-stop-btn{suffix}")
                )
                docling_controls.mount(
                    Button(
                        "Restart", variant="primary", id=f"docling-restart-btn{suffix}"
                    )
                )
            elif docling_starting:
                # Show disabled button or no button when starting
                start_btn = Button(
                    "Starting...", variant="warning", id=f"docling-start-btn{suffix}"
                )
                start_btn.disabled = True
                docling_controls.mount(start_btn)
            else:
                docling_controls.mount(
                    Button("Start", variant="success", id=f"docling-start-btn{suffix}")
                )

        except Exception as e:
            notify_with_diagnostics(
                self.app, f"Error updating docling controls: {e}", severity="error"
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
            selected_service = self._get_selected_service()
            if selected_service:
                # Push the logs screen with the selected service
                from .logs import LogsScreen

                logs_screen = LogsScreen(initial_service=selected_service)
                self.app.push_screen(logs_screen)
            else:
                self.notify("No service selected", severity="warning")
        except Exception as e:
            self.notify(f"Error opening logs: {e}", severity="error")

    def _get_selected_service(self) -> str | None:
        """Resolve the currently selected service based on active table."""
        try:
            active_table = self._get_active_table_name()

            if active_table == "docling" and self.docling_table:
                cursor = self._get_cursor_row(self.docling_table)
                if cursor is not None and cursor >= 0:
                    return "docling-serve"

            services_table = self.query_one("#services-table", DataTable)
            row_count = self._table_row_count(services_table)
            if row_count == 0:
                return None

            cursor = self._get_cursor_row(services_table)
            if cursor is None or cursor < 0 or cursor >= row_count:
                cursor = 0

            row_data = services_table.get_row_at(cursor)
            if not row_data:
                return None

            service_name = str(row_data[0])
            service_mapping = {
                "openrag-backend": "openrag-backend",
                "openrag-frontend": "openrag-frontend",
                "opensearch": "opensearch",
                "langflow": "langflow",
                "dashboards": "dashboards",
            }
            return service_mapping.get(service_name, service_name)
        except Exception as e:
            self.notify(f"Error getting selected service: {e}", severity="error")
            return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection events to ensure mutual exclusivity."""
        selected_table = event.data_table

        try:
            # Track which table was selected
            if selected_table.id == "services-table":
                self._focus_services_table(row="current")
            elif selected_table.id == "docling-table":
                self._focus_docling_table()
        except Exception:
            # Ignore errors during table manipulation
            pass

    def _get_active_table_name(self) -> str:
        """Determine which table is currently active."""
        if self.docling_table and self.docling_table.has_focus:
            return "docling"
        if self.services_table and self.services_table.has_focus:
            return "services"
        return self._last_selected_table or "services"

    def _table_row_count(self, table: DataTable | None) -> int:
        """Safely compute the number of rows in a DataTable."""
        if not table:
            return 0

        count_attr = getattr(table, "row_count", None)
        if callable(count_attr):
            try:
                return int(count_attr())
            except Exception:
                pass

        if isinstance(count_attr, int):
            return count_attr

        try:
            rows = getattr(table, "rows", None)
            if rows is not None:
                return len(rows)
        except Exception:
            pass

        return 0

    def _get_cursor_row(self, table: DataTable | None) -> int | None:
        """Return the current cursor row for the given table."""
        if not table:
            return None

        coord = getattr(table, "cursor_coordinate", None)
        if coord is None:
            return None

        row = getattr(coord, "row", None)
        if row is not None:
            return row

        if isinstance(coord, tuple) and coord:
            return coord[0]

        return None

    def _set_cursor_row(self, table: DataTable | None, row: int) -> None:
        """Set the cursor row for the given table, if possible."""
        if not table:
            return

        try:
            table.cursor_coordinate = (row, 0)
        except Exception:
            move_cursor = getattr(table, "move_cursor", None)
            if callable(move_cursor):
                try:
                    move_cursor(row, 0, expand=False)
                except Exception:
                    pass

    def _focus_services_table(
        self, row: str | None = None, set_last: bool = True
    ) -> None:
        """Focus the services table and update selection."""
        if not self.services_table:
            return

        try:
            self.services_table.focus()
            row_count = self._table_row_count(self.services_table)

            if row_count:
                if row == "last":
                    self._set_cursor_row(self.services_table, row_count - 1)
                elif row == "current":
                    # Keep existing cursor position if valid
                    cursor = self._get_cursor_row(self.services_table)
                    if cursor is None or cursor < 0 or cursor >= row_count:
                        self._set_cursor_row(self.services_table, 0)
                else:
                    cursor = self._get_cursor_row(self.services_table)
                    if cursor is None or cursor < 0:
                        self._set_cursor_row(self.services_table, 0)

            if set_last:
                self._last_selected_table = "services"
        except Exception:
            pass

    def _focus_docling_table(self, focus: bool = True, set_last: bool = True) -> None:
        """Focus the docling table and select its row."""
        if not self.docling_table:
            return

        try:
            if focus:
                self.docling_table.focus()

            if self._table_row_count(self.docling_table):
                self._set_cursor_row(self.docling_table, 0)

            if set_last:
                self._last_selected_table = "docling"
        except Exception:
            pass
