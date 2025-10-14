"""Container lifecycle manager for OpenRAG TUI."""

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, AsyncIterator
from utils.logging_config import get_logger
try:
    from importlib.resources import files
except ImportError:
    from importlib_resources import files

logger = get_logger(__name__)

from ..utils.platform import PlatformDetector, RuntimeInfo, RuntimeType
from utils.gpu_detection import detect_gpu_devices


class ServiceStatus(Enum):
    """Container service status."""

    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"
    MISSING = "missing"


@dataclass
class ServiceInfo:
    """Container service information."""

    name: str
    status: ServiceStatus
    health: Optional[str] = None
    ports: List[str] = field(default_factory=list)
    image: Optional[str] = None
    image_digest: Optional[str] = None
    created: Optional[str] = None

    def __post_init__(self):
        if self.ports is None:
            self.ports = []


class ContainerManager:
    """Manages Docker/Podman container lifecycle for OpenRAG."""

    def __init__(self, compose_file: Optional[Path] = None):
        self.platform_detector = PlatformDetector()
        self.runtime_info = self.platform_detector.detect_runtime()
        self.compose_file = compose_file or self._find_compose_file("docker-compose.yml")
        self.cpu_compose_file = self._find_compose_file("docker-compose-cpu.yml")
        self.services_cache: Dict[str, ServiceInfo] = {}
        self.last_status_update = 0
        # Auto-select CPU compose if no GPU available
        try:
            has_gpu, _ = detect_gpu_devices()
            self.use_cpu_compose = not has_gpu
        except Exception:
            self.use_cpu_compose = True

        # Expected services based on compose files
        self.expected_services = [
            "openrag-backend",
            "openrag-frontend",
            "opensearch",
            "dashboards",
            "langflow",
        ]

        # Map container names to service names
        self.container_name_map = {
            "openrag-backend": "openrag-backend",
            "openrag-frontend": "openrag-frontend",
            "os": "opensearch",
            "osdash": "dashboards",
            "langflow": "langflow",
        }

    def _find_compose_file(self, filename: str) -> Path:
        """Find compose file in current directory or package resources."""
        # First check current working directory
        cwd_path = Path(filename)
        self._compose_search_log = f"Searching for {filename}:\n"
        self._compose_search_log += f"  1. Current directory: {cwd_path.absolute()}"

        if cwd_path.exists():
            self._compose_search_log += " ✓ FOUND"
            return cwd_path
        else:
            self._compose_search_log += " ✗ NOT FOUND"

        # Then check package resources
        self._compose_search_log += f"\n  2. Package resources: "
        try:
            pkg_files = files("tui._assets")
            self._compose_search_log += f"{pkg_files}"
            compose_resource = pkg_files / filename

            if compose_resource.is_file():
                self._compose_search_log += f" ✓ FOUND, copying to current directory"
                # Copy to cwd for compose command to work
                content = compose_resource.read_text()
                cwd_path.write_text(content)
                return cwd_path
            else:
                self._compose_search_log += f" ✗ NOT FOUND"
        except Exception as e:
            self._compose_search_log += f" ✗ SKIPPED ({e})"
            # Don't log this as an error since it's expected when running from source

        # Fall back to original path (will fail later if not found)
        self._compose_search_log += f"\n  3. Falling back to: {cwd_path.absolute()}"
        return Path(filename)

    def is_available(self) -> bool:
        """Check if container runtime is available."""
        return self.runtime_info.runtime_type != RuntimeType.NONE

    def get_runtime_info(self) -> RuntimeInfo:
        """Get container runtime information."""
        return self.runtime_info

    def get_installation_help(self) -> str:
        """Get installation instructions if runtime is not available."""
        return self.platform_detector.get_installation_instructions()

    async def _run_compose_command(
        self, args: List[str], cpu_mode: Optional[bool] = None
    ) -> tuple[bool, str, str]:
        """Run a compose command and return (success, stdout, stderr)."""
        if not self.is_available():
            return False, "", "No container runtime available"

        if cpu_mode is None:
            cpu_mode = self.use_cpu_compose
        compose_file = self.cpu_compose_file if cpu_mode else self.compose_file
        cmd = self.runtime_info.compose_command + ["-f", str(compose_file)] + args

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
            )

            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            success = process.returncode == 0
            return success, stdout_text, stderr_text

        except Exception as e:
            return False, "", f"Command execution failed: {e}"

    async def _run_compose_command_streaming(
        self, args: List[str], cpu_mode: Optional[bool] = None
    ) -> AsyncIterator[tuple[str, bool]]:
        """Run a compose command and yield output with progress bar support.

        Yields:
            Tuples of (message, replace_last) where replace_last indicates if the
            message should replace the previous line (for progress updates)
        """
        if not self.is_available():
            yield ("No container runtime available", False)
            return

        if cpu_mode is None:
            cpu_mode = self.use_cpu_compose
        compose_file = self.cpu_compose_file if cpu_mode else self.compose_file
        cmd = self.runtime_info.compose_command + ["-f", str(compose_file)] + args

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
            )

            if process.stdout:
                buffer = ""
                while True:
                    chunk = await process.stdout.read(1024)
                    if not chunk:
                        if buffer.strip():
                            yield (buffer.strip(), False)
                        break

                    buffer += chunk.decode(errors="ignore")

                    while "\n" in buffer or "\r" in buffer:
                        cr_pos = buffer.find("\r")
                        nl_pos = buffer.find("\n")

                        if cr_pos != -1 and (nl_pos == -1 or cr_pos < nl_pos):
                            line = buffer[:cr_pos]
                            buffer = buffer[cr_pos + 1:]
                            if line.strip():
                                yield (line.strip(), True)
                        elif nl_pos != -1:
                            line = buffer[:nl_pos]
                            buffer = buffer[nl_pos + 1:]
                            if line.strip():
                                yield (line.strip(), False)
                        else:
                            break

            await process.wait()

        except Exception as e:
            yield (f"Command execution failed: {e}", False)

    async def _stream_compose_command(
        self,
        args: List[str],
        success_flag: Dict[str, bool],
        cpu_mode: Optional[bool] = None,
    ) -> AsyncIterator[tuple[str, bool]]:
        """Run compose command with live output and record success/failure.

        Yields:
            Tuples of (message, replace_last) where replace_last indicates if the
            message should replace the previous line (for progress updates)
        """
        if not self.is_available():
            success_flag["value"] = False
            yield ("No container runtime available", False)
            return

        if cpu_mode is None:
            cpu_mode = self.use_cpu_compose
        compose_file = self.cpu_compose_file if cpu_mode else self.compose_file
        cmd = self.runtime_info.compose_command + ["-f", str(compose_file)] + args

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
            )
        except Exception as e:
            success_flag["value"] = False
            yield (f"Command execution failed: {e}", False)
            return

        success_flag["value"] = True

        if process.stdout:
            # Buffer to accumulate data for progress bar handling
            buffer = ""
            while True:
                chunk = await process.stdout.read(1024)
                if not chunk:
                    # Process any remaining buffer content
                    if buffer.strip():
                        yield (buffer.strip(), False)
                    break

                buffer += chunk.decode(errors="ignore")

                # Process complete lines or carriage return updates
                while "\n" in buffer or "\r" in buffer:
                    # Check if we have a carriage return (progress update) before newline
                    cr_pos = buffer.find("\r")
                    nl_pos = buffer.find("\n")

                    if cr_pos != -1 and (nl_pos == -1 or cr_pos < nl_pos):
                        # Carriage return found - extract and yield as replaceable line
                        line = buffer[:cr_pos]
                        buffer = buffer[cr_pos + 1:]
                        if line.strip():
                            yield (line.strip(), True)  # replace_last=True for progress updates
                    elif nl_pos != -1:
                        # Newline found - extract and yield as new line
                        line = buffer[:nl_pos]
                        buffer = buffer[nl_pos + 1:]
                        if line.strip():
                            lowered = line.lower()
                            yield (line.strip(), False)  # replace_last=False for new lines
                            if "error" in lowered or "failed" in lowered:
                                success_flag["value"] = False
                    else:
                        break

        returncode = await process.wait()
        if returncode != 0:
            success_flag["value"] = False
            yield (f"Command exited with status {returncode}", False)

    async def _run_runtime_command(self, args: List[str]) -> tuple[bool, str, str]:
        """Run a runtime command (docker/podman) and return (success, stdout, stderr)."""
        if not self.is_available():
            return False, "", "No container runtime available"

        cmd = self.runtime_info.runtime_command + args

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            success = process.returncode == 0
            return success, stdout_text, stderr_text

        except Exception as e:
            return False, "", f"Command execution failed: {e}"

    def _process_service_json(
        self, service: Dict, services: Dict[str, ServiceInfo]
    ) -> None:
        """Process a service JSON object and add it to the services dict."""
        # Debug print to see the actual service data
        logger.debug("Processing service data", service_data=service)

        container_name = service.get("Name", "")

        # Map container name to service name
        service_name = self.container_name_map.get(container_name)
        if not service_name:
            return

        state = service.get("State", "").lower()

        # Map compose states to our status enum
        if "running" in state:
            status = ServiceStatus.RUNNING
        elif "exited" in state or "stopped" in state:
            status = ServiceStatus.STOPPED
        elif "starting" in state:
            status = ServiceStatus.STARTING
        else:
            status = ServiceStatus.UNKNOWN

        # Extract health - use Status if Health is empty
        health = service.get("Health", "") or service.get("Status", "N/A")

        # Extract ports
        ports_str = service.get("Ports", "")
        ports = (
            [p.strip() for p in ports_str.split(",") if p.strip()] if ports_str else []
        )

        # Extract image
        image = service.get("Image", "N/A")

        services[service_name] = ServiceInfo(
            name=service_name,
            status=status,
            health=health,
            ports=ports,
            image=image,
        )

    async def get_service_status(
        self, force_refresh: bool = False
    ) -> Dict[str, ServiceInfo]:
        """Get current status of all services."""
        current_time = time.time()

        # Use cache if recent and not forcing refresh
        if not force_refresh and current_time - self.last_status_update < 5:
            return self.services_cache

        services = {}

        # Different approach for Podman vs Docker
        if self.runtime_info.runtime_type == RuntimeType.PODMAN:
            # For Podman, use direct podman ps command instead of compose
            cmd = ["ps", "--all", "--format", "json"]
            success, stdout, stderr = await self._run_runtime_command(cmd)

            if success and stdout.strip():
                try:
                    containers = json.loads(stdout.strip())
                    for container in containers:
                        # Get container name and map to service name
                        names = container.get("Names", [])
                        if not names:
                            continue

                        container_name = names[0]
                        service_name = self.container_name_map.get(container_name)
                        if not service_name:
                            continue

                        # Get container state
                        state = container.get("State", "").lower()
                        if "running" in state:
                            status = ServiceStatus.RUNNING
                        elif "exited" in state or "stopped" in state:
                            status = ServiceStatus.STOPPED
                        elif "created" in state:
                            status = ServiceStatus.STARTING
                        else:
                            status = ServiceStatus.UNKNOWN

                        # Get other container info
                        image = container.get("Image", "N/A")
                        ports = []
                        # Handle case where Ports might be None instead of an empty list
                        container_ports = container.get("Ports") or []
                        if isinstance(container_ports, list):
                            for port in container_ports:
                                host_port = port.get("host_port")
                                container_port = port.get("container_port")
                                if host_port and container_port:
                                    ports.append(f"{host_port}:{container_port}")

                        services[service_name] = ServiceInfo(
                            name=service_name,
                            status=status,
                            health=state,
                            ports=ports,
                            image=image,
                        )
                except json.JSONDecodeError:
                    pass
        else:
            # For Docker, use compose ps command
            success, stdout, stderr = await self._run_compose_command(
                ["ps", "--format", "json"]
            )

            if success and stdout.strip():
                try:
                    # Handle both single JSON object (Podman) and multiple JSON objects (Docker)
                    if stdout.strip().startswith("[") and stdout.strip().endswith("]"):
                        # JSON array format
                        service_list = json.loads(stdout.strip())
                        for service in service_list:
                            self._process_service_json(service, services)
                    else:
                        # Line-by-line JSON format
                        for line in stdout.strip().split("\n"):
                            if line.strip() and line.startswith("{"):
                                service = json.loads(line)
                                self._process_service_json(service, services)
                except json.JSONDecodeError:
                    # Fallback to parsing text output
                    lines = stdout.strip().split("\n")
                    if (
                        len(lines) > 1
                    ):  # Make sure we have at least a header and one line
                        for line in lines[1:]:  # Skip header
                            if line.strip():
                                parts = line.split()
                                if len(parts) >= 3:
                                    name = parts[0]

                                    # Only include our expected services
                                    if name not in self.expected_services:
                                        continue

                                    state = parts[2].lower()

                                    if "up" in state:
                                        status = ServiceStatus.RUNNING
                                    elif "exit" in state:
                                        status = ServiceStatus.STOPPED
                                    else:
                                        status = ServiceStatus.UNKNOWN

                                    services[name] = ServiceInfo(
                                        name=name, status=status
                                    )

        # Add expected services that weren't found
        for expected in self.expected_services:
            if expected not in services:
                services[expected] = ServiceInfo(
                    name=expected, status=ServiceStatus.MISSING
                )

        self.services_cache = services
        self.last_status_update = current_time

        return services

    async def get_images_digests(self, images: List[str]) -> Dict[str, str]:
        """Return a map of image -> digest/ID (sha256:...)."""
        digests: Dict[str, str] = {}
        for image in images:
            if not image or image in digests:
                continue
            success, stdout, _ = await self._run_runtime_command(
                ["image", "inspect", image, "--format", "{{.Id}}"]
            )
            if success and stdout.strip():
                digests[image] = stdout.strip().splitlines()[0]
        return digests

    def _extract_images_from_compose_config(self, text: str, tried_json: bool) -> set[str]:
        """
        Try JSON first (if we asked for it or it looks like JSON), then YAML if available.
        Returns a set of image names.
        """
        images: set[str] = set()

        # Try JSON parse
        if tried_json or (text.lstrip().startswith("{") and text.rstrip().endswith("}")):
            try:
                cfg = json.loads(text)
                services = cfg.get("services", {})
                for _, svc in services.items():
                    image = svc.get("image")
                    if image:
                        images.add(str(image))
                if images:
                    return images
            except json.JSONDecodeError:
                pass

        # Try YAML (if available) - import here to avoid hard dependency
        try:
            import yaml
            cfg = yaml.safe_load(text) or {}
            services = cfg.get("services", {})
            if isinstance(services, dict):
                for _, svc in services.items():
                    if isinstance(svc, dict):
                        image = svc.get("image")
                        if image:
                            images.add(str(image))
            if images:
                return images
        except Exception:
            pass

        return images

    async def _parse_compose_images(self) -> list[str]:
        """Get resolved image names from compose files using docker/podman compose, with robust fallbacks."""
        images: set[str] = set()

        compose_files = [self.compose_file, self.cpu_compose_file]
        for compose_file in compose_files:
            try:
                if not compose_file or not compose_file.exists():
                    continue

                cpu_mode = (compose_file == self.cpu_compose_file)

                # Try JSON format first
                success, stdout, _ = await self._run_compose_command(
                    ["config", "--format", "json"],
                    cpu_mode=cpu_mode
                )

                if success and stdout.strip():
                    from_cfg = self._extract_images_from_compose_config(stdout, tried_json=True)
                    if from_cfg:
                        images.update(from_cfg)
                        continue  # this compose file succeeded; move to next file

                # Fallback to YAML output (for older compose versions)
                success, stdout, _ = await self._run_compose_command(
                    ["config"],
                    cpu_mode=cpu_mode
                )

                if success and stdout.strip():
                    from_cfg = self._extract_images_from_compose_config(stdout, tried_json=False)
                    if from_cfg:
                        images.update(from_cfg)
                        continue

            except Exception:
                # Keep behavior resilient—just continue to next file
                continue

        # Fallback: manual parsing if compose config didn't work
        if not images:
            for compose in compose_files:
                try:
                    if not compose.exists():
                        continue
                    for line in compose.read_text().splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("image:"):
                            # image: repo/name:tag
                            val = line.split(":", 1)[1].strip()
                            # Remove quotes if present
                            if (val.startswith('"') and val.endswith('"')) or (
                                val.startswith("'") and val.endswith("'")
                            ):
                                val = val[1:-1]
                            if val:
                                images.add(val)
                except Exception:
                    continue

        return sorted(images)

    async def get_project_images_info(self) -> list[tuple[str, str]]:
        """
        Return list of (image, digest_or_id) for images referenced by compose files.
        If an image isn't present locally, returns '-' for its digest.
        """
        expected = await self._parse_compose_images()
        results: list[tuple[str, str]] = []
        for image in expected:
            digest = "-"
            success, stdout, _ = await self._run_runtime_command(
                ["image", "inspect", image, "--format", "{{.Id}}"]
            )
            if success and stdout.strip():
                digest = stdout.strip().splitlines()[0]
            results.append((image, digest))
        results.sort(key=lambda x: x[0])
        return results

    async def start_services(
        self, cpu_mode: Optional[bool] = None
    ) -> AsyncIterator[tuple[bool, str]]:
        """Start all services and yield progress updates."""
        if not self.is_available():
            yield False, "No container runtime available"
            return

        # Diagnostic info about compose files
        compose_file = self.cpu_compose_file if (cpu_mode if cpu_mode is not None else self.use_cpu_compose) else self.compose_file

        # Show the search process for debugging
        if hasattr(self, '_compose_search_log'):
            for line in self._compose_search_log.split('\n'):
                if line.strip():
                    yield False, line, False

        yield False, f"Final compose file: {compose_file.absolute()}", False
        if not compose_file.exists():
            yield False, f"ERROR: Compose file not found at {compose_file.absolute()}", False
            return

        yield False, "Starting OpenRAG services...", False

        missing_images: List[str] = []
        try:
            images_info = await self.get_project_images_info()
            missing_images = [image for image, digest in images_info if digest == "-"]
        except Exception:
            missing_images = []

        if missing_images:
            images_list = ", ".join(missing_images)
            yield False, f"Pulling container images ({images_list})...", False
            pull_success = {"value": True}
            async for message, replace_last in self._stream_compose_command(
                ["pull"], pull_success, cpu_mode
            ):
                yield False, message, replace_last
            if not pull_success["value"]:
                yield False, "Some images failed to pull; attempting to start services anyway...", False

        yield False, "Creating and starting containers...", False
        up_success = {"value": True}
        async for message, replace_last in self._stream_compose_command(["up", "-d"], up_success, cpu_mode):
            yield False, message, replace_last

        if up_success["value"]:
            yield True, "Services started successfully", False
        else:
            yield False, "Failed to start services. See output above for details.", False

    async def stop_services(self) -> AsyncIterator[tuple[bool, str]]:
        """Stop all services and yield progress updates."""
        yield False, "Stopping OpenRAG services..."

        success, stdout, stderr = await self._run_compose_command(["stop"])

        if success:
            yield True, "Services stopped successfully"
        else:
            yield False, f"Failed to stop services: {stderr}"

    async def restart_services(
        self, cpu_mode: bool = False
    ) -> AsyncIterator[tuple[bool, str]]:
        """Restart all services and yield progress updates."""
        yield False, "Restarting OpenRAG services..."

        success, stdout, stderr = await self._run_compose_command(["restart"], cpu_mode)

        if success:
            yield True, "Services restarted successfully"
        else:
            yield False, f"Failed to restart services: {stderr}"

    async def upgrade_services(
        self, cpu_mode: bool = False
    ) -> AsyncIterator[tuple[bool, str]]:
        """Upgrade services (pull latest images and restart) and yield progress updates."""
        yield False, "Pulling latest images...", False

        # Pull latest images with streaming output
        pull_success = True
        async for message, replace_last in self._run_compose_command_streaming(["pull"], cpu_mode):
            yield False, message, replace_last
            # Check for error patterns in the output
            if "error" in message.lower() or "failed" in message.lower():
                pull_success = False

        if not pull_success:
            yield False, "Failed to pull some images, but continuing with restart...", False

        yield False, "Images updated, restarting services...", False

        # Restart with new images using streaming output
        restart_success = True
        async for message, replace_last in self._run_compose_command_streaming(
            ["up", "-d", "--force-recreate"], cpu_mode
        ):
            yield False, message, replace_last
            # Check for error patterns in the output
            if "error" in message.lower() or "failed" in message.lower():
                restart_success = False

        if restart_success:
            yield True, "Services upgraded and restarted successfully", False
        else:
            yield False, "Some errors occurred during service restart", False

    async def reset_services(self) -> AsyncIterator[tuple[bool, str]]:
        """Reset all services (stop, remove containers/volumes, clear data) and yield progress updates."""
        yield False, "Stopping all services..."

        # Stop and remove everything
        success, stdout, stderr = await self._run_compose_command(
            ["down", "--volumes", "--remove-orphans", "--rmi", "local"]
        )

        if not success:
            yield False, f"Failed to stop services: {stderr}"
            return

        yield False, "Cleaning up container data..."

        # Additional cleanup - remove any remaining containers/volumes
        # This is more thorough than just compose down
        await self._run_runtime_command(["system", "prune", "-f"])

        yield (
            True,
            "System reset completed - all containers, volumes, and local images removed",
        )

    async def get_service_logs(
        self, service_name: str, lines: int = 100
    ) -> tuple[bool, str]:
        """Get logs for a specific service."""
        success, stdout, stderr = await self._run_compose_command(
            ["logs", "--tail", str(lines), service_name]
        )

        if success:
            return True, stdout
        else:
            return False, f"Failed to get logs: {stderr}"

    async def follow_service_logs(self, service_name: str) -> AsyncIterator[str]:
        """Follow logs for a specific service."""
        if not self.is_available():
            yield "No container runtime available"
            return

        compose_file = (
            self.cpu_compose_file if self.use_cpu_compose else self.compose_file
        )
        cmd = self.runtime_info.compose_command + [
            "-f",
            str(compose_file),
            "logs",
            "-f",
            service_name,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
            )

            if process.stdout:
                while True:
                    line = await process.stdout.readline()
                    if line:
                        yield line.decode().rstrip()
                    else:
                        break
            else:
                yield "Error: Unable to read process output"

        except Exception as e:
            yield f"Error following logs: {e}"

    async def get_system_stats(self) -> Dict[str, Dict[str, str]]:
        """Get system resource usage statistics."""
        stats = {}

        # Get container stats
        success, stdout, stderr = await self._run_runtime_command(
            ["stats", "--no-stream", "--format", "json"]
        )

        if success and stdout.strip():
            try:
                for line in stdout.strip().split("\n"):
                    if line.strip():
                        data = json.loads(line)
                        name = data.get("Name", data.get("Container", ""))
                        if name:
                            stats[name] = {
                                "cpu": data.get("CPUPerc", "0%"),
                                "memory": data.get("MemUsage", "0B / 0B"),
                                "memory_percent": data.get("MemPerc", "0%"),
                                "network": data.get("NetIO", "0B / 0B"),
                                "disk": data.get("BlockIO", "0B / 0B"),
                            }
            except json.JSONDecodeError:
                pass

        return stats

    async def debug_podman_services(self) -> str:
        """Run a direct Podman command to check services status for debugging."""
        if self.runtime_info.runtime_type != RuntimeType.PODMAN:
            return "Not using Podman"

        # Try direct podman command
        cmd = ["podman", "ps", "--all", "--format", "json"]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
            )

            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""

            result = f"Command: {' '.join(cmd)}\n"
            result += f"Return code: {process.returncode}\n"
            result += f"Stdout: {stdout_text}\n"
            result += f"Stderr: {stderr_text}\n"

            # Try to parse the output
            if stdout_text.strip():
                try:
                    containers = json.loads(stdout_text)
                    result += f"\nFound {len(containers)} containers:\n"
                    for container in containers:
                        name = container.get("Names", [""])[0]
                        state = container.get("State", "")
                        result += f"  - {name}: {state}\n"
                except json.JSONDecodeError as e:
                    result += f"\nFailed to parse JSON: {e}\n"

            return result

        except Exception as e:
            return f"Error executing command: {e}"

    def check_podman_macos_memory(self) -> tuple[bool, str]:
        """Check if Podman VM has sufficient memory on macOS."""
        if self.runtime_info.runtime_type != RuntimeType.PODMAN:
            return True, "Not using Podman"

        is_sufficient, memory_mb, message = (
            self.platform_detector.check_podman_macos_memory()
        )
        return is_sufficient, message
