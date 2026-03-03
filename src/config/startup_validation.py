"""Preemptive startup validation to catch configuration issues early."""

import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Minimum memory requirements (in MB)
MIN_OPENSEARCH_MEMORY_MB = 2048  # 2GB minimum for OpenSearch
MIN_CONTAINER_MEMORY_MB = 4096  # 4GB minimum for container runtime


class ValidationError(Exception):
    """Raised when startup validation fails."""
    pass


def check_required_env_vars(env: dict = None) -> List[str]:
    """Check for required environment variables.

    Args:
        env: Dictionary of environment variables to check. Defaults to os.environ.

    Returns:
        List of missing required environment variable names.
    """
    if env is None:
        env = os.environ

    missing = []

    # OPENSEARCH_PASSWORD is always required
    if not env.get("OPENSEARCH_PASSWORD"):
        missing.append("OPENSEARCH_PASSWORD")

    # Langflow credentials are required unless AUTO_LOGIN is enabled
    langflow_auto_login = env.get("LANGFLOW_AUTO_LOGIN", "False").lower() in ("true", "1", "yes")

    if not langflow_auto_login:
        if not env.get("LANGFLOW_SUPERUSER"):
            missing.append("LANGFLOW_SUPERUSER")
        if not env.get("LANGFLOW_SUPERUSER_PASSWORD"):
            missing.append("LANGFLOW_SUPERUSER_PASSWORD")

    return missing


def detect_container_runtime() -> Optional[str]:
    """Detect which container runtime is being used.
    
    Returns:
        'docker', 'podman', 'colima', or None if none detected
    """
    # Check for Colima first (it provides docker-compatible API)
    try:
        result = subprocess.run(
            ["colima", "status"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 and "Running" in result.stdout:
            return "colima"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Check for Podman
    try:
        result = subprocess.run(
            ["podman", "info"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return "podman"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Check for Docker (could be Docker Desktop, Docker Engine, or Colima masquerading)
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Check if it's actually Podman masquerading as Docker
            if "podman" in result.stdout.lower():
                return "podman"
            return "docker"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    return None


def check_opensearch_container_memory() -> Tuple[bool, str]:
    """Check if OpenSearch container has sufficient memory.
    
    Returns:
        Tuple of (is_sufficient, error_message)
    """
    container_name = "os"  # OpenSearch container name from docker-compose
    runtime = detect_container_runtime()
    
    if not runtime:
        # No container runtime detected - might be non-containerized environment
        # Assume OK for now
        return True, ""
    
    # Try to check if container exists and get its memory limit
    # Use generic 'docker' command (works with Docker, Podman, and Colima)
    try:
        # Check if container exists
        result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.State.Status}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            # Container doesn't exist yet, which is OK - it might not be started
            # We'll check the container runtime memory instead
            return check_container_runtime_memory(runtime)
        
        # Container exists, check its memory limit
        mem_result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.HostConfig.Memory}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if mem_result.returncode == 0 and mem_result.stdout.strip():
            memory_bytes = int(mem_result.stdout.strip())
            if memory_bytes > 0:
                memory_mb = memory_bytes // (1024 * 1024)
                if memory_mb < MIN_OPENSEARCH_MEMORY_MB:
                    return False, (
                        f"OpenSearch container has insufficient memory: {memory_mb}MB "
                        f"(minimum {MIN_OPENSEARCH_MEMORY_MB}MB required). "
                        f"Increase container memory limit or use a container runtime with more memory."
                    )
                return True, ""
        
        # No explicit memory limit set, check runtime memory
        return check_container_runtime_memory(runtime)
        
    except FileNotFoundError:
        # Docker command not found - shouldn't happen if runtime was detected
        return check_container_runtime_memory(runtime)
    except Exception as e:
        logger.warning("Could not check OpenSearch container memory", error=str(e))
        # Don't fail on check errors, but warn
        return True, ""


def check_container_runtime_memory(runtime: Optional[str] = None) -> Tuple[bool, str]:
    """Check container runtime memory allocation.
    
    Args:
        runtime: Detected runtime ('docker', 'podman', 'colima', or None)
    
    Returns:
        Tuple of (is_sufficient, error_message)
    """
    if runtime is None:
        runtime = detect_container_runtime()
    
    if runtime == "colima":
        # Check Colima VM memory
        try:
            result = subprocess.run(
                ["colima", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                # Colima stores memory in different places depending on version
                memory_mb = None
                if "memory" in status:
                    memory_mb = int(status["memory"])
                elif "vm" in status and "memory" in status["vm"]:
                    memory_mb = int(status["vm"]["memory"])
                
                if memory_mb and memory_mb < MIN_CONTAINER_MEMORY_MB:
                    return False, (
                        f"Colima VM has insufficient memory: {memory_mb}MB "
                        f"(minimum {MIN_CONTAINER_MEMORY_MB}MB recommended for OpenRAG). "
                        f"Stop Colima and restart with more memory:\n"
                        f"  colima stop\n"
                        f"  colima start --memory {MIN_CONTAINER_MEMORY_MB}"
                    )
                if memory_mb:
                    return True, ""
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError, KeyError):
            pass
    
    if runtime == "podman":
        # Check Podman machine memory (macOS/Linux)
        try:
            # Try to list machines and get memory for the default or first one
            list_result = subprocess.run(
                ["podman", "machine", "list", "--format", "{{.Name}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if list_result.returncode == 0 and list_result.stdout.strip():
                machine_name = list_result.stdout.strip().split('\n')[0] or "podman-machine-default"
                
                result = subprocess.run(
                    ["podman", "machine", "inspect", machine_name, "--format", "{{.Resources.Memory}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    memory_mb = int(result.stdout.strip())
                    if memory_mb < MIN_CONTAINER_MEMORY_MB:
                        return False, (
                            f"Podman machine has insufficient memory: {memory_mb}MB "
                            f"(minimum {MIN_CONTAINER_MEMORY_MB}MB recommended for OpenRAG). "
                            f"Recreate Podman machine with more memory:\n"
                            f"  podman machine stop\n"
                            f"  podman machine rm\n"
                            f"  podman machine init --memory {MIN_CONTAINER_MEMORY_MB}\n"
                            f"  podman machine start"
                        )
                    return True, ""
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
    
    # Check Docker/Docker Desktop memory (works for Docker Desktop, Docker Engine, or Colima)
    if runtime in ("docker", "colima", None):
        try:
            # Try to get Docker system info
            result = subprocess.run(
                ["docker", "system", "info", "--format", "{{.MemTotal}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                mem_total = result.stdout.strip()
                # Docker returns memory in various formats, try to parse
                if mem_total and mem_total != "0":
                    # Try to extract number (might be in bytes or human-readable)
                    import re
                    numbers = re.findall(r'\d+', mem_total)
                    if numbers:
                        # Assume it's in bytes if large, MB if small
                        mem_value = int(numbers[0])
                        if mem_value > 1000000:  # Likely bytes
                            memory_mb = mem_value // (1024 * 1024)
                        else:  # Likely MB
                            memory_mb = mem_value
                        
                        if memory_mb < MIN_CONTAINER_MEMORY_MB:
                            runtime_name = "Colima" if runtime == "colima" else "Docker"
                            return False, (
                                f"{runtime_name} has insufficient memory: {memory_mb}MB "
                                f"(minimum {MIN_CONTAINER_MEMORY_MB}MB recommended for OpenRAG). "
                                + (
                                    f"Stop and restart Colima with more memory:\n"
                                    f"  colima stop\n"
                                    f"  colima start --memory {MIN_CONTAINER_MEMORY_MB}"
                                    if runtime == "colima"
                                    else "Increase Docker Desktop memory allocation in settings."
                                )
                            )
                        return True, ""
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass
    
    # If we can't check, assume OK (might be Linux with no limits or non-containerized)
    return True, ""


def validate_startup_requirements():
    """Validate all startup requirements and raise ValidationError if any fail.
    
    Raises:
        ValidationError: If any validation check fails.
    """
    errors = []
    
    # Check required environment variables
    missing_vars = check_required_env_vars()
    if missing_vars:
        error_msg = (
            "Missing required environment variables:\n"
            + "\n".join(f"  - {var}" for var in missing_vars)
            + "\n\n"
            + "Please set these environment variables before starting OpenRAG.\n"
            + "See CONTRIBUTING.md or docs for configuration details."
        )
        errors.append(error_msg)
    
    # Check OpenSearch memory
    memory_ok, memory_error = check_opensearch_container_memory()
    if not memory_ok:
        errors.append(f"Memory check failed:\n  {memory_error}")
    
    # If any errors, raise exception
    if errors:
        error_message = "\n\n".join(errors)
        logger.error("Startup validation failed", errors=errors)
        raise ValidationError(
            "=" * 80 + "\n"
            "STARTUP VALIDATION FAILED\n"
            "=" * 80 + "\n\n"
            + error_message + "\n\n"
            + "=" * 80 + "\n"
            + "Please fix the issues above and restart OpenRAG.\n"
            + "=" * 80
        )
    
    logger.info("Startup validation passed")


if __name__ == "__main__":
    """Run validation as a standalone script."""
    try:
        validate_startup_requirements()
        print("✓ Startup validation passed")
        sys.exit(0)
    except ValidationError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
