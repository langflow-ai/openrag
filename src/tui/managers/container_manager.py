"""Container lifecycle manager for OpenRAG TUI."""

import asyncio
import json
import os
import re
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
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.ports is None:
            self.ports = []


class ContainerManager:
    """Manages Docker/Podman container lifecycle for OpenRAG."""

    def __init__(self, compose_file: Optional[Path] = None):
        self.platform_detector = PlatformDetector()
        self.runtime_info = self.platform_detector.detect_runtime()
        self.compose_file = compose_file or self._find_compose_file("docker-compose.yml")
        self.gpu_compose_file = self._find_compose_file("docker-compose.gpu.yml")
        self.services_cache: Dict[str, ServiceInfo] = {}
        self.last_status_update = 0
        # Auto-select GPU override if GPU is available
        try:
            has_gpu, _ = detect_gpu_devices()
            self.use_gpu_compose = has_gpu
        except Exception:
            self.use_gpu_compose = False

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
        """Find compose file in centralized TUI directory, current directory, or package resources."""
        from utils.paths import get_tui_compose_file
        
        self._compose_search_log = f"Searching for {filename}:\n"
        
        # First check centralized TUI directory (~/.openrag/tui/)
        is_gpu = "gpu" in filename
        tui_path = get_tui_compose_file(gpu=is_gpu)
        self._compose_search_log += f"  1. TUI directory: {tui_path.absolute()}"
        
        if tui_path.exists():
            self._compose_search_log += " ✓ FOUND"
            return tui_path
        else:
            self._compose_search_log += " ✗ NOT FOUND"
        
        # Then check current working directory (for backward compatibility)
        cwd_path = Path(filename)
        self._compose_search_log += f"\n  2. Current directory: {cwd_path.absolute()}"

        if cwd_path.exists():
            self._compose_search_log += " ✓ FOUND"
            return cwd_path
        else:
            self._compose_search_log += " ✗ NOT FOUND"

        # Finally check package resources
        self._compose_search_log += f"\n  3. Package resources: "
        try:
            pkg_files = files("tui._assets")
            self._compose_search_log += f"{pkg_files}"
            compose_resource = pkg_files / filename

            if compose_resource.is_file():
                self._compose_search_log += f" ✓ FOUND, copying to TUI directory"
                # Copy to TUI directory
                tui_path.parent.mkdir(parents=True, exist_ok=True)
                content = compose_resource.read_text()
                tui_path.write_text(content)
                return tui_path
            else:
                self._compose_search_log += f" ✗ NOT FOUND"
        except Exception as e:
            self._compose_search_log += f" ✗ SKIPPED ({e})"
            # Don't log this as an error since it's expected when running from source

        # Fall back to TUI path (will fail later if not found)
        self._compose_search_log += f"\n  4. Falling back to: {tui_path.absolute()}"
        return tui_path

    def _get_env_from_file(self) -> Dict[str, str]:
        """Read environment variables from .env file, prioritizing file values over os.environ.
        
        Uses python-dotenv's load_dotenv() for standard .env file parsing, which handles:
        - Quoted values (single and double quotes)
        - Variable expansion (${VAR})
        - Multiline values
        - Escaped characters
        - Comments
        
        This ensures Docker Compose commands use the latest values from .env file,
        even if os.environ has stale values.
        """
        from dotenv import load_dotenv
        from utils.paths import get_tui_env_file
        
        env = dict(os.environ)  # Start with current environment
        
        # Check centralized TUI .env location first
        tui_env_file = get_tui_env_file()
        if tui_env_file.exists():
            env_file = tui_env_file
        else:
            # Fall back to CWD .env for backward compatibility
            env_file = Path(".env")
        
        if env_file.exists():
            try:
                # Load .env file with override=True to ensure file values take precedence
                # This loads into os.environ, then we copy to our dict
                load_dotenv(dotenv_path=env_file, override=True)
                # Update our dict with all environment variables (including those from .env)
                env.update(os.environ)
                logger.debug(f"Loaded environment from {env_file}")
            except Exception as e:
                logger.debug(f"Error reading .env file for Docker Compose: {e}")
        
        return env

    def is_available(self) -> bool:
        """Check if container runtime with compose is available."""
        return (self.runtime_info.runtime_type != RuntimeType.NONE and
                len(self.runtime_info.compose_command) > 0)

    def get_runtime_info(self) -> RuntimeInfo:
        """Get container runtime information."""
        return self.runtime_info

    def get_installation_help(self) -> str:
        """Get installation instructions based on what's missing."""
        if self.runtime_info.has_runtime_without_compose:
            return self.platform_detector.get_compose_installation_instructions()
        return self.platform_detector.get_installation_instructions()

    def _extract_ports_from_compose(self) -> Dict[str, List[int]]:
        """Extract port mappings from compose files.
        
        Returns:
            Dict mapping service name to list of host ports
        """
        service_ports: Dict[str, List[int]] = {}
        
        compose_files = [self.compose_file]
        if hasattr(self, 'cpu_compose_file') and self.cpu_compose_file and self.cpu_compose_file.exists():
            compose_files.append(self.cpu_compose_file)
        
        for compose_file in compose_files:
            if not compose_file.exists():
                continue
                
            try:
                content = compose_file.read_text()
                current_service = None
                in_ports_section = False
                
                for line in content.splitlines():
                    # Detect service names
                    service_match = re.match(r'^  (\w[\w-]*):$', line)
                    if service_match:
                        current_service = service_match.group(1)
                        in_ports_section = False
                        if current_service not in service_ports:
                            service_ports[current_service] = []
                        continue
                    
                    # Detect ports section
                    if current_service and re.match(r'^    ports:$', line):
                        in_ports_section = True
                        continue
                    
                    # Exit ports section on new top-level key
                    if in_ports_section and re.match(r'^    \w+:', line):
                        in_ports_section = False
                    
                    # Extract port mappings
                    if in_ports_section and current_service:
                        # Match patterns like: - "3000:3000", - "9200:9200", - 7860:7860
                        port_match = re.search(r'["\']?(\d+):\d+["\']?', line)
                        if port_match:
                            host_port = int(port_match.group(1))
                            if host_port not in service_ports[current_service]:
                                service_ports[current_service].append(host_port)
                                
            except Exception as e:
                logger.debug(f"Error parsing {compose_file} for ports: {e}")
                continue
        
        return service_ports

    async def check_ports_available(self) -> tuple[bool, List[tuple[str, int, str]]]:
        """Check if required ports are available.
        
        Returns:
            Tuple of (all_available, conflicts) where conflicts is a list of
            (service_name, port, error_message) tuples
        """
        import socket
        
        service_ports = self._extract_ports_from_compose()
        conflicts: List[tuple[str, int, str]] = []
        
        for service_name, ports in service_ports.items():
            for port in ports:
                try:
                    # Try to bind to the port to check if it's available
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    result = sock.connect_ex(('127.0.0.1', port))
                    sock.close()
                    
                    if result == 0:
                        # Port is in use
                        conflicts.append((
                            service_name,
                            port,
                            f"Port {port} is already in use"
                        ))
                except Exception as e:
                    logger.debug(f"Error checking port {port}: {e}")
                    continue
        
        return (len(conflicts) == 0, conflicts)

    async def _run_compose_command(
        self, args: List[str], cpu_mode: Optional[bool] = None
    ) -> tuple[bool, str, str]:
        """Run a compose command and return (success, stdout, stderr)."""
        if not self.is_available():
            return False, "", "No container runtime available"

        if cpu_mode is None:
            use_gpu = self.use_gpu_compose
        else:
            use_gpu = not cpu_mode
        
        # Build compose command with override pattern
        cmd = self.runtime_info.compose_command.copy()
        
        # Add --env-file to explicitly specify the .env location
        from utils.paths import get_tui_env_file
        tui_env_file = get_tui_env_file()
        if tui_env_file.exists():
            cmd.extend(["--env-file", str(tui_env_file)])
        elif Path(".env").exists():
            cmd.extend(["--env-file", ".env"])
        
        cmd.extend(["-f", str(self.compose_file)])
        if use_gpu and self.gpu_compose_file.exists():
            cmd.extend(["-f", str(self.gpu_compose_file)])
        cmd.extend(args)

        try:
            # Get environment variables from .env file to ensure latest values
            env = self._get_env_from_file()
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
                env=env,
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
            use_gpu = self.use_gpu_compose
        else:
            use_gpu = not cpu_mode
        
        # Build compose command with override pattern
        cmd = self.runtime_info.compose_command.copy()
        
        # Add --env-file to explicitly specify the .env location
        from utils.paths import get_tui_env_file
        tui_env_file = get_tui_env_file()
        if tui_env_file.exists():
            cmd.extend(["--env-file", str(tui_env_file)])
        elif Path(".env").exists():
            cmd.extend(["--env-file", ".env"])
        
        cmd.extend(["-f", str(self.compose_file)])
        if use_gpu and self.gpu_compose_file.exists():
            cmd.extend(["-f", str(self.gpu_compose_file)])
        cmd.extend(args)

        try:
            # Get environment variables from .env file to ensure latest values
            env = self._get_env_from_file()
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
                env=env,
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
            use_gpu = self.use_gpu_compose
        else:
            use_gpu = not cpu_mode
        
        # Build compose command with override pattern
        cmd = self.runtime_info.compose_command.copy()
        
        # Add --env-file to explicitly specify the .env location
        from utils.paths import get_tui_env_file
        tui_env_file = get_tui_env_file()
        if tui_env_file.exists():
            cmd.extend(["--env-file", str(tui_env_file)])
        elif Path(".env").exists():
            cmd.extend(["--env-file", ".env"])
        
        cmd.extend(["-f", str(self.compose_file)])
        if use_gpu and self.gpu_compose_file.exists():
            cmd.extend(["-f", str(self.gpu_compose_file)])
        cmd.extend(args)

        try:
            # Get environment variables from .env file to ensure latest values
            env = self._get_env_from_file()
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
                env=env,
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

    async def get_container_version(self) -> Optional[str]:
        """
        Get the version tag from existing containers.
        Checks the backend container image tag to determine version.
        
        Returns:
            Version string if found, None if no containers exist or version can't be determined
        """
        try:
            # Check for backend container first (most reliable)
            success, stdout, _ = await self._run_runtime_command(
                ["ps", "--all", "--filter", "name=openrag-backend", "--format", "{{.Image}}"]
            )
            
            if success and stdout.strip():
                image_tag = stdout.strip().splitlines()[0].strip()
                if not image_tag or image_tag == "N/A":
                    return None
                
                # Extract version from image tag (e.g., langflowai/openrag-backend:0.1.47)
                if ":" in image_tag:
                    version = image_tag.split(":")[-1]
                    # If version is "latest", check .env file for OPENRAG_VERSION
                    if version == "latest":
                        # Try to get version from .env file
                        try:
                            from pathlib import Path
                            env_file = Path(".env")
                            if env_file.exists():
                                env_content = env_file.read_text()
                                for line in env_content.splitlines():
                                    line = line.strip()
                                    if line.startswith("OPENRAG_VERSION"):
                                        env_version = line.split("=", 1)[1].strip()
                                        # Remove quotes if present
                                        env_version = env_version.strip("'\"")
                                        if env_version and env_version != "latest":
                                            return env_version
                        except Exception:
                            pass
                        # If still "latest", we can't determine version - return None
                        return None
                    # Return version if it looks like a version number (not "latest")
                    if version and version != "latest":
                        return version
            
            # Fallback: check all containers for version tags
            success, stdout, _ = await self._run_runtime_command(
                ["ps", "--all", "--format", "{{.Image}}"]
            )
            
            if success and stdout.strip():
                images = stdout.strip().splitlines()
                for image in images:
                    image = image.strip()
                    if "openrag" in image.lower() and ":" in image:
                        version = image.split(":")[-1]
                        if version and version != "latest":
                            return version
        except Exception as e:
            logger.debug(f"Error getting container version: {e}")
        
        return None

    async def check_version_mismatch(self) -> tuple[bool, Optional[str], str]:
        """
        Check if existing containers have a different version than the current TUI.
        
        Returns:
            Tuple of (has_mismatch, container_version, tui_version)
        """
        try:
            from ..utils.version_check import get_current_version
            
            tui_version = get_current_version()
            if tui_version == "unknown":
                return False, None, tui_version
            
            container_version = await self.get_container_version()
            
            if container_version is None:
                # No containers exist, no mismatch
                return False, None, tui_version
            
            # Compare versions
            from ..utils.version_check import compare_versions
            comparison = compare_versions(container_version, tui_version)
            has_mismatch = comparison != 0
            
            return has_mismatch, container_version, tui_version
        except Exception as e:
            logger.debug(f"Error checking version mismatch: {e}")
            return False, None, "unknown"

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
        from utils.paths import get_tui_env_file
        
        images: set[str] = set()

        # Try both GPU and CPU modes to get all images
        for use_gpu in [True, False]:
            try:
                # Build compose command with override pattern
                cmd = self.runtime_info.compose_command.copy()
                
                # Add --env-file to explicitly specify the .env location
                tui_env_file = get_tui_env_file()
                if tui_env_file.exists():
                    cmd.extend(["--env-file", str(tui_env_file)])
                elif Path(".env").exists():
                    cmd.extend(["--env-file", ".env"])
                
                cmd.extend(["-f", str(self.compose_file)])
                if use_gpu and self.gpu_compose_file.exists():
                    cmd.extend(["-f", str(self.gpu_compose_file)])
                cmd.extend(["config", "--format", "json"])

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=Path.cwd(),
                )
                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode() if stdout else ""

                if process.returncode == 0 and stdout_text.strip():
                    from_cfg = self._extract_images_from_compose_config(stdout_text, tried_json=True)
                    if from_cfg:
                        images.update(from_cfg)
                        continue

                # Fallback to YAML output (for older compose versions)
                cmd = self.runtime_info.compose_command.copy()
                
                # Add --env-file to explicitly specify the .env location
                tui_env_file = get_tui_env_file()
                if tui_env_file.exists():
                    cmd.extend(["--env-file", str(tui_env_file)])
                elif Path(".env").exists():
                    cmd.extend(["--env-file", ".env"])
                
                cmd.extend(["-f", str(self.compose_file)])
                if use_gpu and self.gpu_compose_file.exists():
                    cmd.extend(["-f", str(self.gpu_compose_file)])
                cmd.append("config")

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=Path.cwd(),
                )
                stdout, stderr = await process.communicate()
                stdout_text = stdout.decode() if stdout else ""

                if process.returncode == 0 and stdout_text.strip():
                    from_cfg = self._extract_images_from_compose_config(stdout_text, tried_json=False)
                    if from_cfg:
                        images.update(from_cfg)
                        continue

            except Exception:
                # Keep behavior resilient—just continue to next mode
                continue

        # Fallback: manual parsing if compose config didn't work
        if not images:
            compose_files = [self.compose_file]
            if self.gpu_compose_file.exists():
                compose_files.append(self.gpu_compose_file)
            
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

        # Ensure OPENRAG_VERSION is set in .env file
        try:
            from ..managers.env_manager import EnvManager
            env_manager = EnvManager()
            env_manager.ensure_openrag_version()
        except Exception:
            pass  # Continue even if version setting fails

        # Determine GPU mode
        if cpu_mode is None:
            use_gpu = self.use_gpu_compose
        else:
            use_gpu = not cpu_mode

        # Show the search process for debugging
        if hasattr(self, '_compose_search_log'):
            for line in self._compose_search_log.split('\n'):
                if line.strip():
                    yield False, line, False

        # Show runtime detection info
        runtime_cmd_str = " ".join(self.runtime_info.compose_command)
        yield False, f"Using compose command: {runtime_cmd_str}", False
        compose_files_str = str(self.compose_file.absolute())
        if use_gpu and self.gpu_compose_file.exists():
            compose_files_str += f" + {self.gpu_compose_file.absolute()}"
        yield False, f"Compose files: {compose_files_str}", False
        if not self.compose_file.exists():
            yield False, f"ERROR: Base compose file not found at {self.compose_file.absolute()}", False
            return

        # Check for port conflicts before starting
        yield False, "Checking port availability...", False
        ports_available, conflicts = await self.check_ports_available()
        if not ports_available:
            yield False, "ERROR: Port conflicts detected:", False
            for service_name, port, error_msg in conflicts:
                yield False, f"  - {service_name}: {error_msg}", False
            yield False, "Please stop the conflicting services and try again.", False
            yield False, "Services not started due to port conflicts.", False
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

        # Check if containers already exist (stopped or otherwise)
        # Use compose ps -q to check for any existing containers in the project
        success, stdout, stderr = await self._run_compose_command(["ps", "-q"])
        containers_exist = success and stdout.strip() != ""

        if containers_exist:
            yield False, "Starting existing containers...", False
            if self.runtime_info.runtime_type == RuntimeType.PODMAN:
                # Podman doesn't support --no-recreate; force-recreate to avoid
                # "name already in use" and dependency graph errors
                compose_cmd = ["up", "-d", "--force-recreate"]
            else:
                # Use --no-recreate to start existing containers without recreating
                compose_cmd = ["up", "-d", "--no-recreate"]
        else:
            yield False, "Creating and starting containers...", False
            compose_cmd = ["up", "-d", "--no-build"]

        up_success = {"value": True}
        error_messages = []

        async for message, replace_last in self._stream_compose_command(compose_cmd, up_success, cpu_mode):
            # Detect error patterns in the output
            lower_msg = message.lower()
            
            # Check for common error patterns
            if any(pattern in lower_msg for pattern in [
                "port.*already.*allocated",
                "address already in use",
                "bind.*address already in use",
                "port is already allocated"
            ]):
                error_messages.append("Port conflict detected")
                up_success["value"] = False
            elif "error" in lower_msg or "failed" in lower_msg:
                # Generic error detection
                if message not in error_messages:
                    error_messages.append(message)
            
            yield False, message, replace_last

        if up_success["value"]:
            yield True, "Services started successfully", False
        else:
            yield False, "Failed to start services. See output above for details.", False
            if error_messages:
                yield False, "\nDetected errors:", False
                for err in error_messages[:5]:  # Limit to first 5 errors
                    yield False, f"  - {err}", False

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
            ["up", "-d", "--force-recreate", "--no-build"], cpu_mode
        ):
            yield False, message, replace_last
            # Check for error patterns in the output
            if "error" in message.lower() or "failed" in message.lower():
                restart_success = False

        if restart_success:
            yield True, "Services upgraded and restarted successfully", False
        else:
            yield False, "Some errors occurred during service restart", False

    async def clear_directory_with_container(self, path: Path) -> tuple[bool, str]:
        """Clear a directory using a container to handle container-owned files.

        Args:
            path: The directory to clear (contents will be deleted, directory recreated)

        Returns:
            Tuple of (success, message)
        """
        if not self.is_available():
            return False, "No container runtime available"

        if not path.exists():
            return True, "Directory does not exist, nothing to clear"

        path = path.absolute()

        # Use alpine container to delete files owned by container user
        cmd = [
            "run", "--rm",
            "-v", f"{path}:/work:Z",
            "alpine",
            "sh", "-c",
            "rm -rf /work/* /work/.[!.]* 2>/dev/null; echo done"
        ]

        success, stdout, stderr = await self._run_runtime_command(cmd)

        if success and "done" in stdout:
            return True, f"Cleared {path}"
        else:
            return False, f"Failed to clear {path}: {stderr or 'Unknown error'}"

    async def clear_opensearch_data_volume(self) -> AsyncIterator[tuple[bool, str]]:
        """Clear opensearch data using a temporary container with proper permissions."""
        if not self.is_available():
            yield False, "No container runtime available"
            return

        yield False, "Clearing OpenSearch data volume..."

        # Get opensearch data path from env config
        from .env_manager import EnvManager
        env_manager = EnvManager()
        env_manager.load_existing_env()
        opensearch_data_path = Path(env_manager.config.opensearch_data_path.replace("$HOME", str(Path.home()))).expanduser().absolute()

        if not opensearch_data_path.exists():
            yield True, "OpenSearch data directory does not exist, skipping"
            return

        # Use alpine with root to clear container-owned files
        success, msg = await self.clear_directory_with_container(opensearch_data_path)

        if success:
            yield True, "OpenSearch data cleared successfully"
        else:
            yield False, f"Failed to clear OpenSearch data: {msg}"

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

        # Build compose command with override pattern
        cmd = self.runtime_info.compose_command.copy() + ["-f", str(self.compose_file)]
        if self.use_gpu_compose and self.gpu_compose_file.exists():
            cmd.extend(["-f", str(self.gpu_compose_file)])
        cmd.extend(["logs", "-f", service_name])

        try:
            # Get environment variables from .env file to ensure latest values
            env = self._get_env_from_file()
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd(),
                env=env,
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

    async def prune_old_images(self) -> AsyncIterator[tuple[bool, str]]:
        """Prune old OpenRAG images and dependencies, keeping only the latest versions.
        
        This method:
        1. Lists all images
        2. Identifies OpenRAG-related images (openrag-backend, openrag-frontend, langflow, opensearch, dashboards)
        3. For each repository, keeps only the latest/currently used image
        4. Removes old images
        5. Prunes dangling images
        
        Yields:
            Tuples of (success, message) for progress updates
        """
        if not self.is_available():
            yield False, "No container runtime available"
            return

        yield False, "Scanning for OpenRAG images..."

        # Get list of all images
        success, stdout, stderr = await self._run_runtime_command(
            ["images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}"]
        )

        if not success:
            yield False, f"Failed to list images: {stderr}"
            return

        # Parse images and group by repository
        openrag_repos = {
            "langflowai/openrag-backend",
            "langflowai/openrag-frontend",
            "langflowai/openrag-langflow",
            "langflowai/openrag-opensearch",
            "langflowai/openrag-dashboards",
            "langflow/langflow",  # Also include base langflow images
            "opensearchproject/opensearch",
            "opensearchproject/opensearch-dashboards",
        }

        images_by_repo = {}
        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            
            image_tag, image_id, created_at = parts[0], parts[1], parts[2]
            
            # Skip <none> tags (dangling images will be handled separately)
            if "<none>" in image_tag:
                continue
            
            # Extract repository name (without tag)
            if ":" in image_tag:
                repo = image_tag.rsplit(":", 1)[0]
            else:
                repo = image_tag
            
            # Check if this is an OpenRAG-related image
            if any(openrag_repo in repo for openrag_repo in openrag_repos):
                if repo not in images_by_repo:
                    images_by_repo[repo] = []
                images_by_repo[repo].append({
                    "full_tag": image_tag,
                    "id": image_id,
                    "created": created_at,
                })

        if not images_by_repo:
            yield True, "No OpenRAG images found to prune"
            # Still run dangling image cleanup
            yield False, "Cleaning up dangling images..."
            success, stdout, stderr = await self._run_runtime_command(
                ["image", "prune", "-f"]
            )
            if success:
                yield True, "Dangling images cleaned up"
            else:
                yield False, f"Failed to prune dangling images: {stderr}"
            return

        # Get currently used images (from running/stopped containers)
        services = await self.get_service_status(force_refresh=True)
        current_images = set()
        for service_info in services.values():
            if service_info.image and service_info.image != "N/A":
                current_images.add(service_info.image)

        yield False, f"Found {len(images_by_repo)} OpenRAG image repositories"

        # For each repository, remove old images (keep latest and currently used)
        total_removed = 0
        for repo, images in images_by_repo.items():
            if len(images) <= 1:
                # Only one image for this repo, skip
                continue

            # Sort by creation date (newest first)
            # Note: This is a simple string comparison which works for ISO dates
            images.sort(key=lambda x: x["created"], reverse=True)

            # Keep the newest image and any currently used images
            images_to_remove = []
            for i, img in enumerate(images):
                # Keep the first (newest) image
                if i == 0:
                    continue
                # Keep currently used images
                if img["full_tag"] in current_images:
                    continue
                # Mark for removal
                images_to_remove.append(img)

            if not images_to_remove:
                yield False, f"No old images to remove for {repo}"
                continue

            # Remove old images
            for img in images_to_remove:
                yield False, f"Removing old image: {img['full_tag']}"
                success, stdout, stderr = await self._run_runtime_command(
                    ["rmi", img["id"]]
                )
                if success:
                    total_removed += 1
                    yield False, f"  ✓ Removed {img['full_tag']}"
                else:
                    # Don't fail the whole operation if one image fails
                    # (might be in use by another container)
                    yield False, f"  ⚠ Could not remove {img['full_tag']}: {stderr.strip()}"

        if total_removed > 0:
            yield True, f"Removed {total_removed} old image(s)"
        else:
            yield True, "No old images were removed"

        # Clean up dangling images (untagged images)
        yield False, "Cleaning up dangling images..."
        success, stdout, stderr = await self._run_runtime_command(
            ["image", "prune", "-f"]
        )
        
        if success:
            # Parse output to see if anything was removed
            if stdout.strip():
                yield True, f"Dangling images cleaned: {stdout.strip()}"
            else:
                yield True, "No dangling images to clean"
        else:
            yield False, f"Failed to prune dangling images: {stderr}"

        yield True, "Image pruning completed"

    async def prune_all_images(self) -> AsyncIterator[tuple[bool, str]]:
        """Stop services and prune ALL OpenRAG images and dependencies.
        
        This is a more aggressive pruning that:
        1. Stops all running services
        2. Removes ALL OpenRAG-related images (not just old versions)
        3. Prunes dangling images
        
        This frees up maximum disk space but requires re-downloading images on next start.
        
        Yields:
            Tuples of (success, message) for progress updates
        """
        if not self.is_available():
            yield False, "No container runtime available"
            return

        # Step 1: Stop all services first
        yield False, "Stopping all services..."
        async for success, message in self.stop_services():
            yield success, message
            if not success and "failed" in message.lower():
                yield False, "Failed to stop services, aborting prune"
                return

        # Give services time to fully stop
        import asyncio
        await asyncio.sleep(2)

        yield False, "Scanning for OpenRAG images..."

        # Get list of all images
        success, stdout, stderr = await self._run_runtime_command(
            ["images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}"]
        )

        if not success:
            yield False, f"Failed to list images: {stderr}"
            return

        # Parse images and identify ALL OpenRAG-related images
        openrag_repos = {
            "langflowai/openrag-backend",
            "langflowai/openrag-frontend",
            "langflowai/openrag-langflow",
            "langflowai/openrag-opensearch",
            "langflowai/openrag-dashboards",
            "langflow/langflow",
            "opensearchproject/opensearch",
            "opensearchproject/opensearch-dashboards",
        }

        images_to_remove = []
        for line in stdout.strip().split("\n"):
            if not line.strip():
                continue
            
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            
            image_tag, image_id = parts[0], parts[1]
            
            # Skip <none> tags (will be handled by prune)
            if "<none>" in image_tag:
                continue
            
            # Extract repository name (without tag)
            if ":" in image_tag:
                repo = image_tag.rsplit(":", 1)[0]
            else:
                repo = image_tag
            
            # Check if this is an OpenRAG-related image
            if any(openrag_repo in repo for openrag_repo in openrag_repos):
                images_to_remove.append({
                    "full_tag": image_tag,
                    "id": image_id,
                })

        if not images_to_remove:
            yield True, "No OpenRAG images found to remove"
        else:
            yield False, f"Found {len(images_to_remove)} OpenRAG image(s) to remove"

            # Remove all OpenRAG images
            total_removed = 0
            for img in images_to_remove:
                yield False, f"Removing image: {img['full_tag']}"
                success, stdout, stderr = await self._run_runtime_command(
                    ["rmi", "-f", img["id"]]  # Force remove
                )
                if success:
                    total_removed += 1
                    yield False, f"  ✓ Removed {img['full_tag']}"
                else:
                    yield False, f"  ⚠ Could not remove {img['full_tag']}: {stderr.strip()}"

            if total_removed > 0:
                yield True, f"Removed {total_removed} OpenRAG image(s)"
            else:
                yield False, "No images were removed"

        # Clean up dangling images
        yield False, "Cleaning up dangling images..."
        success, stdout, stderr = await self._run_runtime_command(
            ["image", "prune", "-f"]
        )
        
        if success:
            if stdout.strip():
                yield True, f"Dangling images cleaned: {stdout.strip()}"
            else:
                yield True, "No dangling images to clean"
        else:
            yield False, f"Failed to prune dangling images: {stderr}"

        yield True, "All OpenRAG images removed successfully"

