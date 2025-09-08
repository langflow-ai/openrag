"""Diagnostics screen for OpenRAG TUI."""

import asyncio
import logging
import os
import datetime
from pathlib import Path
from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, Label, Log
from rich.text import Text

from ..managers.container_manager import ContainerManager


class DiagnosticsScreen(Screen):
    """Diagnostics screen for debugging OpenRAG."""

    CSS = """
    #diagnostics-log {
        border: solid $accent;
        padding: 1;
        margin: 1;
        background: $surface;
        min-height: 20;
    }
    
    .button-row Button {
        margin: 0 1;
    }
    
    .copy-indicator {
        background: $success;
        color: $text;
        padding: 1;
        margin: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "back", "Back"),
        ("r", "refresh", "Refresh"),
        ("ctrl+c", "copy", "Copy to Clipboard"),
        ("ctrl+s", "save", "Save to File"),
    ]

    def __init__(self):
        super().__init__()
        self.container_manager = ContainerManager()
        self._logger = logging.getLogger("openrag.diagnostics")
        self._status_timer = None

    def compose(self) -> ComposeResult:
        """Create the diagnostics screen layout."""
        yield Header()
        with Container(id="main-container"):
            yield Static("OpenRAG Diagnostics", classes="tab-header")
            with Horizontal(classes="button-row"):
                yield Button("Refresh", variant="primary", id="refresh-btn")
                yield Button("Check Podman", variant="default", id="check-podman-btn")
                yield Button("Check Docker", variant="default", id="check-docker-btn")
                yield Button("Copy to Clipboard", variant="default", id="copy-btn")
                yield Button("Save to File", variant="default", id="save-btn")
                yield Button("Back", variant="default", id="back-btn")

            # Status indicator for copy/save operations
            yield Static("", id="copy-status", classes="copy-indicator")

            with ScrollableContainer(id="diagnostics-scroll"):
                yield Log(id="diagnostics-log", highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the screen."""
        self.run_diagnostics()

        # Focus the first button (refresh-btn)
        try:
            self.query_one("#refresh-btn").focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-btn":
            self.action_refresh()
        elif event.button.id == "check-podman-btn":
            asyncio.create_task(self.check_podman())
        elif event.button.id == "check-docker-btn":
            asyncio.create_task(self.check_docker())
        elif event.button.id == "copy-btn":
            self.copy_to_clipboard()
        elif event.button.id == "save-btn":
            self.save_to_file()
        elif event.button.id == "back-btn":
            self.action_back()

    def action_refresh(self) -> None:
        """Refresh diagnostics."""
        self.run_diagnostics()

    def action_copy(self) -> None:
        """Copy log content to clipboard (keyboard shortcut)."""
        self.copy_to_clipboard()

    def copy_to_clipboard(self) -> None:
        """Copy log content to clipboard."""
        try:
            log = self.query_one("#diagnostics-log", Log)
            content = "\n".join(str(line) for line in log.lines)
            status = self.query_one("#copy-status", Static)

            # Try to use pyperclip if available
            try:
                import pyperclip

                pyperclip.copy(content)
                self.notify("Copied to clipboard", severity="information")
                status.update("✓ Content copied to clipboard")
                self._hide_status_after_delay(status)
                return
            except ImportError:
                pass

            # Fallback to platform-specific clipboard commands
            import subprocess
            import platform

            system = platform.system()
            if system == "Darwin":  # macOS
                process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
                process.communicate(input=content)
                self.notify("Copied to clipboard", severity="information")
                status.update("✓ Content copied to clipboard")
            elif system == "Windows":
                process = subprocess.Popen(["clip"], stdin=subprocess.PIPE, text=True)
                process.communicate(input=content)
                self.notify("Copied to clipboard", severity="information")
                status.update("✓ Content copied to clipboard")
            elif system == "Linux":
                # Try xclip first, then xsel
                try:
                    process = subprocess.Popen(
                        ["xclip", "-selection", "clipboard"],
                        stdin=subprocess.PIPE,
                        text=True,
                    )
                    process.communicate(input=content)
                    self.notify("Copied to clipboard", severity="information")
                    status.update("✓ Content copied to clipboard")
                except FileNotFoundError:
                    try:
                        process = subprocess.Popen(
                            ["xsel", "--clipboard", "--input"],
                            stdin=subprocess.PIPE,
                            text=True,
                        )
                        process.communicate(input=content)
                        self.notify("Copied to clipboard", severity="information")
                        status.update("✓ Content copied to clipboard")
                    except FileNotFoundError:
                        self.notify(
                            "Clipboard utilities not found. Install xclip or xsel.",
                            severity="error",
                        )
                        status.update(
                            "❌ Clipboard utilities not found. Install xclip or xsel."
                        )
            else:
                self.notify(
                    "Clipboard not supported on this platform", severity="error"
                )
                status.update("❌ Clipboard not supported on this platform")

            self._hide_status_after_delay(status)
        except Exception as e:
            self.notify(f"Failed to copy to clipboard: {e}", severity="error")
            status = self.query_one("#copy-status", Static)
            status.update(f"❌ Failed to copy: {e}")
            self._hide_status_after_delay(status)

    def _hide_status_after_delay(
        self, status_widget: Static, delay: float = 3.0
    ) -> None:
        """Hide the status message after a delay."""
        # Cancel any existing timer
        if self._status_timer:
            self._status_timer.cancel()

        # Create and run the timer task
        self._status_timer = asyncio.create_task(
            self._clear_status_after_delay(status_widget, delay)
        )

    async def _clear_status_after_delay(
        self, status_widget: Static, delay: float
    ) -> None:
        """Clear the status message after a delay."""
        await asyncio.sleep(delay)
        status_widget.update("")

    def action_save(self) -> None:
        """Save log content to file (keyboard shortcut)."""
        self.save_to_file()

    def save_to_file(self) -> None:
        """Save log content to a file."""
        try:
            log = self.query_one("#diagnostics-log", Log)
            content = "\n".join(str(line) for line in log.lines)
            status = self.query_one("#copy-status", Static)

            # Create logs directory if it doesn't exist
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)

            # Create a timestamped filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = logs_dir / f"openrag_diagnostics_{timestamp}.txt"

            # Save to file
            with open(filename, "w") as f:
                f.write(content)

            self.notify(f"Saved to {filename}", severity="information")
            status.update(f"✓ Saved to {filename}")

            # Log the save operation
            self._logger.info(f"Diagnostics saved to {filename}")
            self._hide_status_after_delay(status)
        except Exception as e:
            error_msg = f"Failed to save file: {e}"
            self.notify(error_msg, severity="error")
            self._logger.error(error_msg)

            status = self.query_one("#copy-status", Static)
            status.update(f"❌ {error_msg}")
            self._hide_status_after_delay(status)

    def action_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()

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

        return info_text

    def run_diagnostics(self) -> None:
        """Run all diagnostics."""
        log = self.query_one("#diagnostics-log", Log)
        log.clear()

        # System information
        system_info = self._get_system_info()
        log.write(str(system_info))
        log.write("")

        # Run async diagnostics
        asyncio.create_task(self._run_async_diagnostics())

    async def _run_async_diagnostics(self) -> None:
        """Run asynchronous diagnostics."""
        log = self.query_one("#diagnostics-log", Log)

        # Check services
        log.write("[bold green]Service Status[/bold green]")
        services = await self.container_manager.get_service_status(force_refresh=True)
        for name, info in services.items():
            status_color = "green" if info.status == "running" else "red"
            log.write(
                f"[bold]{name}[/bold]: [{status_color}]{info.status.value}[/{status_color}]"
            )
            if info.health:
                log.write(f"  Health: {info.health}")
            if info.ports:
                log.write(f"  Ports: {', '.join(info.ports)}")
            if info.image:
                log.write(f"  Image: {info.image}")
        log.write("")

        # Check for Podman-specific issues
        if self.container_manager.runtime_info.runtime_type.name == "PODMAN":
            await self.check_podman()

    async def check_podman(self) -> None:
        """Run Podman-specific diagnostics."""
        log = self.query_one("#diagnostics-log", Log)
        log.write("[bold green]Podman Diagnostics[/bold green]")

        # Check if using Podman
        if self.container_manager.runtime_info.runtime_type.name != "PODMAN":
            log.write("[yellow]Not using Podman[/yellow]")
            return

        # Check Podman version
        cmd = ["podman", "--version"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write(f"Podman version: {stdout.decode().strip()}")
        else:
            log.write(
                f"[red]Failed to get Podman version: {stderr.decode().strip()}[/red]"
            )

        # Check Podman containers
        cmd = ["podman", "ps", "--all"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write("Podman containers:")
            for line in stdout.decode().strip().split("\n"):
                log.write(f"  {line}")
        else:
            log.write(
                f"[red]Failed to list Podman containers: {stderr.decode().strip()}[/red]"
            )

        # Check Podman compose
        cmd = ["podman", "compose", "ps"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.container_manager.compose_file.parent,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write("Podman compose services:")
            for line in stdout.decode().strip().split("\n"):
                log.write(f"  {line}")
        else:
            log.write(
                f"[red]Failed to list Podman compose services: {stderr.decode().strip()}[/red]"
            )

        log.write("")

    async def check_docker(self) -> None:
        """Run Docker-specific diagnostics."""
        log = self.query_one("#diagnostics-log", Log)
        log.write("[bold green]Docker Diagnostics[/bold green]")

        # Check if using Docker
        if "DOCKER" not in self.container_manager.runtime_info.runtime_type.name:
            log.write("[yellow]Not using Docker[/yellow]")
            return

        # Check Docker version
        cmd = ["docker", "--version"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write(f"Docker version: {stdout.decode().strip()}")
        else:
            log.write(
                f"[red]Failed to get Docker version: {stderr.decode().strip()}[/red]"
            )

        # Check Docker containers
        cmd = ["docker", "ps", "--all"]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write("Docker containers:")
            for line in stdout.decode().strip().split("\n"):
                log.write(f"  {line}")
        else:
            log.write(
                f"[red]Failed to list Docker containers: {stderr.decode().strip()}[/red]"
            )

        # Check Docker compose
        cmd = ["docker", "compose", "ps"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.container_manager.compose_file.parent,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            log.write("Docker compose services:")
            for line in stdout.decode().strip().split("\n"):
                log.write(f"  {line}")
        else:
            log.write(
                f"[red]Failed to list Docker compose services: {stderr.decode().strip()}[/red]"
            )

        log.write("")


# Made with Bob
