"""Platform detection and container runtime discovery utilities."""

import json
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RuntimeType(Enum):
    DOCKER_COMPOSE = "docker-compose"
    DOCKER = "docker"
    PODMAN = "podman"
    NONE = "none"


@dataclass
class RuntimeInfo:
    runtime_type: RuntimeType
    compose_command: list[str]
    runtime_command: list[str]
    version: Optional[str] = None


class PlatformDetector:
    """Detect platform and container runtime capabilities."""

    def __init__(self):
        self.platform_system = platform.system()
        self.platform_machine = platform.machine()

    def is_native_windows(self) -> bool:
        """
        Check if running on native Windows (not WSL).

        Returns True if running on native Windows, False otherwise.
        WSL environments will return False since they identify as Linux.
        """
        return self.platform_system == "Windows"

    def detect_runtime(self) -> RuntimeInfo:
        """Detect available container runtime and compose capabilities."""
        # First check if we have podman installed
        podman_version = self._get_podman_version()

        # If we have podman, check if docker is actually podman in disguise
        if podman_version:
            docker_version = self._get_docker_version()
            if docker_version and podman_version in docker_version:
                # This is podman masquerading as docker
                if self._check_command(["docker", "compose", "--help"]):
                    return RuntimeInfo(
                        RuntimeType.PODMAN,
                        ["docker", "compose"],
                        ["docker"],
                        podman_version,
                    )
                if self._check_command(["docker-compose", "--help"]):
                    return RuntimeInfo(
                        RuntimeType.PODMAN,
                        ["docker-compose"],
                        ["docker"],
                        podman_version,
                    )

            # Check for native podman compose
            if self._check_command(["podman", "compose", "--help"]):
                return RuntimeInfo(
                    RuntimeType.PODMAN,
                    ["podman", "compose"],
                    ["podman"],
                    podman_version,
                )

        # Check for actual docker
        if self._check_command(["docker", "compose", "--help"]):
            version = self._get_docker_version()
            return RuntimeInfo(
                RuntimeType.DOCKER, ["docker", "compose"], ["docker"], version
            )
        if self._check_command(["docker-compose", "--help"]):
            version = self._get_docker_version()
            return RuntimeInfo(
                RuntimeType.DOCKER_COMPOSE, ["docker-compose"], ["docker"], version
            )

        return RuntimeInfo(RuntimeType.NONE, [], [])

    def detect_gpu_available(self) -> bool:
        """Best-effort detection of NVIDIA GPU availability for containers."""
        try:
            res = subprocess.run(
                ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0 and any(
                "GPU" in ln for ln in res.stdout.splitlines()
            ):
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        for cmd in (
            ["docker", "info", "--format", "{{json .Runtimes}}"],
            ["podman", "info", "--format", "json"],
        ):
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0 and "nvidia" in res.stdout.lower():
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
        return False

    def _check_command(self, cmd: list[str]) -> bool:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_docker_version(self) -> Optional[str]:
        try:
            res = subprocess.run(
                ["docker", "--version"], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _get_podman_version(self) -> Optional[str]:
        try:
            res = subprocess.run(
                ["podman", "--version"], capture_output=True, text=True, timeout=5
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def check_podman_macos_memory(self) -> tuple[bool, int, str]:
        """
        Check Podman VM memory on macOS.

        Returns (is_sufficient, current_memory_mb, status_message)
        """
        if self.platform_system != "Darwin":
            return True, 0, "Not running on macOS"
        try:
            result = subprocess.run(
                ["podman", "machine", "inspect"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False, 0, "Could not inspect Podman machine"
            machines = json.loads(result.stdout)
            if not machines:
                return False, 0, "No Podman machines found"
            machine = machines[0]
            memory_mb = machine.get("Resources", {}).get("Memory", 0)
            min_memory_mb = 8192
            is_sufficient = memory_mb >= min_memory_mb
            status = f"Current: {memory_mb}MB, Recommended: ≥{min_memory_mb}MB"
            if not is_sufficient:
                status += "\nTo increase: podman machine stop && podman machine rm && podman machine init --memory 8192 && podman machine start"
            return is_sufficient, memory_mb, status
        except (
            subprocess.TimeoutExpired,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as e:
            return False, 0, f"Error checking Podman VM memory: {e}"

    def get_wsl_recommendation(self) -> str:
        """Get recommendation message for native Windows users to use WSL."""
        return """
⚠️  Running on native Windows detected.

For the best experience, we recommend using Windows Subsystem for Linux (WSL).

To set up WSL:
  1. Open PowerShell or Command Prompt as Administrator
  2. Run: wsl --install
  3. Restart your computer
  4. Set up your Linux distribution (Ubuntu recommended)
  5. Install Docker or Podman in WSL

Learn more: https://docs.microsoft.com/en-us/windows/wsl/install
"""

    def get_installation_instructions(self) -> str:
        if self.platform_system == "Darwin":
            return """
No container runtime found. Please install one:

Docker Desktop for Mac:
  https://docs.docker.com/desktop/install/mac-install/

Or Podman:
  brew install podman
  podman machine init --memory 8192
  podman machine start
"""
        elif self.platform_system == "Linux":
            return """
No container runtime found. Please install one:

Docker:
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh

Or Podman:
  # Ubuntu/Debian: sudo apt install podman
  # RHEL/Fedora: sudo dnf install podman
"""
        elif self.platform_system == "Windows":
            return """
No container runtime found. Please install one:

Docker Desktop for Windows:
  https://docs.docker.com/desktop/install/windows-install/

Or Podman Desktop:
  https://podman-desktop.io/downloads

For better performance, consider using WSL:
  Run: wsl --install
  https://docs.microsoft.com/en-us/windows/wsl/install
"""
        else:
            return """
No container runtime found. Please install Docker or Podman for your platform:
  - Docker: https://docs.docker.com/get-docker/
  - Podman: https://podman.io/getting-started/installation
"""
