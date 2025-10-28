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
from textual.widgets import Header, Footer, Static, Button, Log
from rich.text import Text

from ..managers.container_manager import ContainerManager
from ..utils.clipboard import copy_text_to_clipboard
from ..utils.platform import PlatformDetector


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
        self.platform_detector = PlatformDetector()
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
                yield Button("Check OpenSearch Security", variant="default", id="check-opensearch-security-btn")
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
        elif event.button.id == "check-opensearch-security-btn":
            asyncio.create_task(self.check_opensearch_security())
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

            success, message = copy_text_to_clipboard(content)
            if success:
                self.notify(message, severity="information")
                status.update(f"✓ {message}")
            else:
                self.notify(message, severity="error")
                status.update(f"❌ {message}")

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

        # Platform information
        info_text.append("Platform Information\n", style="bold")
        info_text.append("=" * 30 + "\n")
        info_text.append(f"System: {self.platform_detector.platform_system}\n")
        info_text.append(f"Machine: {self.platform_detector.platform_machine}\n")

        # Windows-specific warning
        if self.platform_detector.is_native_windows():
            info_text.append("\n")
            info_text.append("⚠️  Native Windows Detected\n", style="bold yellow")
            info_text.append("-" * 30 + "\n")
            info_text.append(self.platform_detector.get_wsl_recommendation())
            info_text.append("\n")

        info_text.append("\n")

        # Container runtime information
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

    async def check_opensearch_security(self) -> None:
        """Run OpenSearch security configuration diagnostics."""
        log = self.query_one("#diagnostics-log", Log)
        log.write("[bold green]OpenSearch Security Diagnostics[/bold green]")

        # Get OpenSearch password from environment or prompt user that it's needed
        opensearch_password = os.getenv("OPENSEARCH_PASSWORD")
        if not opensearch_password:
            log.write("[red]OPENSEARCH_PASSWORD environment variable not set[/red]")
            log.write("[yellow]Set OPENSEARCH_PASSWORD to test security configuration[/yellow]")
            log.write("")
            return

        # Test basic authentication
        log.write("Testing basic authentication...")
        cmd = [
            "curl", "-s", "-k", "-w", "%{http_code}",
            "-u", f"admin:{opensearch_password}",
            "https://localhost:9200"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            response = stdout.decode().strip()
            # Extract HTTP status code (last 3 characters)
            if len(response) >= 3:
                status_code = response[-3:]
                response_body = response[:-3]
                if status_code == "200":
                    log.write("[green]✓ Basic authentication successful[/green]")
                    try:
                        import json
                        info = json.loads(response_body)
                        if "version" in info and "distribution" in info["version"]:
                            log.write(f"  OpenSearch version: {info['version']['number']}")
                    except:
                        pass
                else:
                    log.write(f"[red]✗ Basic authentication failed with status {status_code}[/red]")
            else:
                log.write("[red]✗ Unexpected response from OpenSearch[/red]")
        else:
            log.write(f"[red]✗ Failed to connect to OpenSearch: {stderr.decode().strip()}[/red]")

        # Test security plugin account info
        log.write("Testing security plugin account info...")
        cmd = [
            "curl", "-s", "-k", "-w", "%{http_code}",
            "-u", f"admin:{opensearch_password}",
            "https://localhost:9200/_plugins/_security/api/account"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            response = stdout.decode().strip()
            if len(response) >= 3:
                status_code = response[-3:]
                response_body = response[:-3]
                if status_code == "200":
                    log.write("[green]✓ Security plugin accessible[/green]")
                    try:
                        import json
                        user_info = json.loads(response_body)
                        if "user_name" in user_info:
                            log.write(f"  Current user: {user_info['user_name']}")
                        if "roles" in user_info:
                            log.write(f"  Roles: {', '.join(user_info['roles'])}")
                        if "tenants" in user_info:
                            tenants = list(user_info['tenants'].keys())
                            log.write(f"  Tenants: {', '.join(tenants)}")
                    except:
                        log.write("  Account info retrieved but couldn't parse JSON")
                else:
                    log.write(f"[red]✗ Security plugin returned status {status_code}[/red]")
        else:
            log.write(f"[red]✗ Failed to access security plugin: {stderr.decode().strip()}[/red]")

        # Test internal users
        log.write("Testing internal users configuration...")
        cmd = [
            "curl", "-s", "-k", "-w", "%{http_code}",
            "-u", f"admin:{opensearch_password}",
            "https://localhost:9200/_plugins/_security/api/internalusers"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            response = stdout.decode().strip()
            if len(response) >= 3:
                status_code = response[-3:]
                response_body = response[:-3]
                if status_code == "200":
                    try:
                        import json
                        users = json.loads(response_body)
                        if "admin" in users:
                            log.write("[green]✓ Admin user configured[/green]")
                            admin_user = users["admin"]
                            if admin_user.get("reserved"):
                                log.write("  Admin user is reserved (protected)")
                        log.write(f"  Total internal users: {len(users)}")
                    except:
                        log.write("[green]✓ Internal users endpoint accessible[/green]")
                else:
                    log.write(f"[red]✗ Internal users returned status {status_code}[/red]")
        else:
            log.write(f"[red]✗ Failed to access internal users: {stderr.decode().strip()}[/red]")

        # Test authentication domains configuration
        log.write("Testing authentication configuration...")
        cmd = [
            "curl", "-s", "-k", "-w", "%{http_code}",
            "-u", f"admin:{opensearch_password}",
            "https://localhost:9200/_plugins/_security/api/securityconfig"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            response = stdout.decode().strip()
            if len(response) >= 3:
                status_code = response[-3:]
                response_body = response[:-3]
                if status_code == "200":
                    try:
                        import json
                        config = json.loads(response_body)
                        if "config" in config and "dynamic" in config["config"] and "authc" in config["config"]["dynamic"]:
                            authc = config["config"]["dynamic"]["authc"]
                            if "openid_auth_domain" in authc:
                                log.write("[green]✓ OpenID Connect authentication domain configured[/green]")
                                oidc_config = authc["openid_auth_domain"].get("http_authenticator", {}).get("config", {})
                                if "openid_connect_url" in oidc_config:
                                    log.write(f"  OIDC URL: {oidc_config['openid_connect_url']}")
                                if "subject_key" in oidc_config:
                                    log.write(f"  Subject key: {oidc_config['subject_key']}")
                            if "basic_internal_auth_domain" in authc:
                                log.write("[green]✓ Basic internal authentication domain configured[/green]")
                            
                            # Check for multi-tenancy
                            if "kibana" in config["config"]["dynamic"]:
                                kibana_config = config["config"]["dynamic"]["kibana"]
                                if kibana_config.get("multitenancy_enabled"):
                                    log.write("[green]✓ Multi-tenancy enabled[/green]")
                        else:
                            log.write("[yellow]⚠ Authentication configuration not found in expected format[/yellow]")
                    except Exception as e:
                        log.write("[green]✓ Security config endpoint accessible[/green]")
                        log.write(f"  (Could not parse JSON: {str(e)[:50]}...)")
                else:
                    log.write(f"[red]✗ Security config returned status {status_code}[/red]")
        else:
            log.write(f"[red]✗ Failed to access security config: {stderr.decode().strip()}[/red]")

        # Test indices with potential security filtering
        log.write("Testing index access...")
        cmd = [
            "curl", "-s", "-k", "-w", "%{http_code}",
            "-u", f"admin:{opensearch_password}",
            "https://localhost:9200/_cat/indices?v"
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            response = stdout.decode().strip()
            if len(response) >= 3:
                status_code = response[-3:]
                response_body = response[:-3]
                if status_code == "200":
                    log.write("[green]✓ Index listing accessible[/green]")
                    lines = response_body.strip().split('\n')
                    if len(lines) > 1:  # Skip header
                        indices_found = []
                        for line in lines[1:]:
                            if 'documents' in line:
                                indices_found.append('documents')
                            elif 'knowledge_filters' in line:
                                indices_found.append('knowledge_filters')
                            elif '.opendistro_security' in line:
                                indices_found.append('.opendistro_security')
                        if indices_found:
                            log.write(f"  Key indices found: {', '.join(indices_found)}")
                else:
                    log.write(f"[red]✗ Index listing returned status {status_code}[/red]")
        else:
            log.write(f"[red]✗ Failed to list indices: {stderr.decode().strip()}[/red]")

        log.write("")


# Made with Bob
