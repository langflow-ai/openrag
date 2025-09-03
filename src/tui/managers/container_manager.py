"""Container lifecycle manager for OpenRAG TUI."""

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, AsyncIterator

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
    ports: List[str] = None
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
        self.compose_file = compose_file or Path("docker-compose.yml")
        self.cpu_compose_file = Path("docker-compose-cpu.yml")
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
            "langflow"
        ]
        
        # Map container names to service names
        self.container_name_map = {
            "openrag-backend": "openrag-backend",
            "openrag-frontend": "openrag-frontend",
            "os": "opensearch", 
            "osdash": "dashboards",
            "langflow": "langflow"
        }
    
    def is_available(self) -> bool:
        """Check if container runtime is available."""
        return self.runtime_info.runtime_type != RuntimeType.NONE
    
    def get_runtime_info(self) -> RuntimeInfo:
        """Get container runtime information."""
        return self.runtime_info
    
    def get_installation_help(self) -> str:
        """Get installation instructions if runtime is not available."""
        return self.platform_detector.get_installation_instructions()
    
    async def _run_compose_command(self, args: List[str], cpu_mode: Optional[bool] = None) -> tuple[bool, str, str]:
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
                cwd=Path.cwd()
            )
            
            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""
            
            success = process.returncode == 0
            return success, stdout_text, stderr_text
            
        except Exception as e:
            return False, "", f"Command execution failed: {e}"
    
    async def _run_runtime_command(self, args: List[str]) -> tuple[bool, str, str]:
        """Run a runtime command (docker/podman) and return (success, stdout, stderr)."""
        if not self.is_available():
            return False, "", "No container runtime available"
        
        cmd = self.runtime_info.runtime_command + args
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""
            
            success = process.returncode == 0
            return success, stdout_text, stderr_text
            
        except Exception as e:
            return False, "", f"Command execution failed: {e}"
    
    async def get_service_status(self, force_refresh: bool = False) -> Dict[str, ServiceInfo]:
        """Get current status of all services."""
        current_time = time.time()
        
        # Use cache if recent and not forcing refresh
        if not force_refresh and current_time - self.last_status_update < 5:
            return self.services_cache
        
        services = {}
        
        # Get compose service status
        success, stdout, stderr = await self._run_compose_command(["ps", "--format", "json"])
        
        if success and stdout.strip():
            try:
                # Parse JSON output - each line is a separate JSON object
                for line in stdout.strip().split('\n'):
                    if line.strip() and line.startswith('{'):
                        service = json.loads(line)
                        container_name = service.get("Name", "")
                        
                        # Map container name to service name
                        service_name = self.container_name_map.get(container_name)
                        if not service_name:
                            continue
                            
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
                        ports = [p.strip() for p in ports_str.split(",") if p.strip()] if ports_str else []
                        
                        # Extract image
                        image = service.get("Image", "N/A")
                        
                        services[service_name] = ServiceInfo(
                            name=service_name,
                            status=status,
                            health=health,
                            ports=ports,
                            image=image,
                        )
                        
            except json.JSONDecodeError:
                # Fallback to parsing text output
                lines = stdout.strip().split('\n')
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
                            
                            services[name] = ServiceInfo(name=name, status=status)
        
        # Add expected services that weren't found
        for expected in self.expected_services:
            if expected not in services:
                services[expected] = ServiceInfo(name=expected, status=ServiceStatus.MISSING)
        
        self.services_cache = services
        self.last_status_update = current_time
        
        return services

    async def get_images_digests(self, images: List[str]) -> Dict[str, str]:
        """Return a map of image -> digest/ID (sha256:...)."""
        digests: Dict[str, str] = {}
        for image in images:
            if not image or image in digests:
                continue
            success, stdout, _ = await self._run_runtime_command([
                "image", "inspect", image, "--format", "{{.Id}}"
            ])
            if success and stdout.strip():
                digests[image] = stdout.strip().splitlines()[0]
        return digests

    def _parse_compose_images(self) -> list[str]:
        """Best-effort parse of image names from compose files without YAML dependency."""
        images: set[str] = set()
        for compose in [self.compose_file, self.cpu_compose_file]:
            try:
                if not compose.exists():
                    continue
                for line in compose.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('image:'):
                        # image: repo/name:tag
                        val = line.split(':', 1)[1].strip()
                        # Remove quotes if present
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        images.add(val)
            except Exception:
                continue
        return list(images)

    async def get_project_images_info(self) -> list[tuple[str, str]]:
        """
        Return list of (image, digest_or_id) for images referenced by compose files.
        If an image isn't present locally, returns '-' for its digest.
        """
        expected = self._parse_compose_images()
        results: list[tuple[str, str]] = []
        for image in expected:
            digest = '-'
            success, stdout, _ = await self._run_runtime_command([
                'image', 'inspect', image, '--format', '{{.Id}}'
            ])
            if success and stdout.strip():
                digest = stdout.strip().splitlines()[0]
            results.append((image, digest))
        results.sort(key=lambda x: x[0])
        return results
    
    async def start_services(self, cpu_mode: bool = False) -> AsyncIterator[tuple[bool, str]]:
        """Start all services and yield progress updates."""
        yield False, "Starting OpenRAG services..."
        
        success, stdout, stderr = await self._run_compose_command(["up", "-d"], cpu_mode)
        
        if success:
            yield True, "Services started successfully"
        else:
            yield False, f"Failed to start services: {stderr}"
    
    async def stop_services(self) -> AsyncIterator[tuple[bool, str]]:
        """Stop all services and yield progress updates."""
        yield False, "Stopping OpenRAG services..."
        
        success, stdout, stderr = await self._run_compose_command(["down"])
        
        if success:
            yield True, "Services stopped successfully"
        else:
            yield False, f"Failed to stop services: {stderr}"
    
    async def restart_services(self, cpu_mode: bool = False) -> AsyncIterator[tuple[bool, str]]:
        """Restart all services and yield progress updates."""
        yield False, "Restarting OpenRAG services..."
        
        success, stdout, stderr = await self._run_compose_command(["restart"], cpu_mode)
        
        if success:
            yield True, "Services restarted successfully"
        else:
            yield False, f"Failed to restart services: {stderr}"
    
    async def upgrade_services(self, cpu_mode: bool = False) -> AsyncIterator[tuple[bool, str]]:
        """Upgrade services (pull latest images and restart) and yield progress updates."""
        yield False, "Pulling latest images..."
        
        # Pull latest images
        success, stdout, stderr = await self._run_compose_command(["pull"], cpu_mode)
        
        if not success:
            yield False, f"Failed to pull images: {stderr}"
            return
        
        yield False, "Images updated, restarting services..."
        
        # Restart with new images
        success, stdout, stderr = await self._run_compose_command(["up", "-d", "--force-recreate"], cpu_mode)
        
        if success:
            yield True, "Services upgraded and restarted successfully"
        else:
            yield False, f"Failed to restart services after upgrade: {stderr}"
    
    async def reset_services(self) -> AsyncIterator[tuple[bool, str]]:
        """Reset all services (stop, remove containers/volumes, clear data) and yield progress updates."""
        yield False, "Stopping all services..."
        
        # Stop and remove everything
        success, stdout, stderr = await self._run_compose_command([
            "down", 
            "--volumes", 
            "--remove-orphans", 
            "--rmi", "local"
        ])
        
        if not success:
            yield False, f"Failed to stop services: {stderr}"
            return
        
        yield False, "Cleaning up container data..."
        
        # Additional cleanup - remove any remaining containers/volumes
        # This is more thorough than just compose down
        await self._run_runtime_command(["system", "prune", "-f"])
        
        yield True, "System reset completed - all containers, volumes, and local images removed"
    
    async def get_service_logs(self, service_name: str, lines: int = 100) -> tuple[bool, str]:
        """Get logs for a specific service."""
        success, stdout, stderr = await self._run_compose_command(["logs", "--tail", str(lines), service_name])
        
        if success:
            return True, stdout
        else:
            return False, f"Failed to get logs: {stderr}"
    
    async def follow_service_logs(self, service_name: str) -> AsyncIterator[str]:
        """Follow logs for a specific service."""
        if not self.is_available():
            yield "No container runtime available"
            return
        
        compose_file = self.cpu_compose_file if self.use_cpu_compose else self.compose_file
        cmd = self.runtime_info.compose_command + ["-f", str(compose_file), "logs", "-f", service_name]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path.cwd()
            )
            
            while True:
                line = await process.stdout.readline()
                if line:
                    yield line.decode().rstrip()
                else:
                    break
                    
        except Exception as e:
            yield f"Error following logs: {e}"
    
    async def get_system_stats(self) -> Dict[str, Dict[str, str]]:
        """Get system resource usage statistics."""
        stats = {}
        
        # Get container stats
        success, stdout, stderr = await self._run_runtime_command(["stats", "--no-stream", "--format", "json"])
        
        if success and stdout.strip():
            try:
                for line in stdout.strip().split('\n'):
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
    
    def check_podman_macos_memory(self) -> tuple[bool, str]:
        """Check if Podman VM has sufficient memory on macOS."""
        if self.runtime_info.runtime_type != RuntimeType.PODMAN:
            return True, "Not using Podman"
        
        return self.platform_detector.check_podman_macos_memory()[:2]  # Return is_sufficient, message
