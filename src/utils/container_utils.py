"""Utilities for detecting and working with container environments."""

import os
from pathlib import Path


def detect_container_environment() -> str | None:
    """Detect if running in a container and return the appropriate container type.

    Returns:
        'docker' if running in Docker, 'podman' if running in Podman, None otherwise.
    """
    # Check for .dockerenv file (Docker)
    if Path("/.dockerenv").exists():
        return "docker"

    # Check cgroup for container indicators
    try:
        with Path("/proc/self/cgroup").open() as f:
            content = f.read()
            if "docker" in content:
                return "docker"
            if "podman" in content:
                return "podman"
    except (FileNotFoundError, PermissionError):
        pass

    # Check environment variables (lowercase 'container' is the standard for Podman)
    if os.getenv("container") == "podman":  # noqa: SIM112
        return "podman"

    return None


def get_container_host() -> str | None:
    """Get the hostname to access host services from within a container.

    Tries multiple methods to find the correct hostname:
    1. host.containers.internal (Podman) or host.docker.internal (Docker)
    2. Gateway IP from routing table (fallback for Linux)

    Returns:
        The hostname or IP to use, or None if not in a container.
    """
    import socket

    # Check if we're in a container first
    container_type = detect_container_environment()
    if not container_type:
        return None

    # Try container-specific hostnames first based on detected type
    if container_type == "podman":
        # Podman: try host.containers.internal first
        try:
            socket.getaddrinfo("host.containers.internal", None)
        except socket.gaierror:
            pass
        else:
            return "host.containers.internal"

        # Fallback to host.docker.internal (for Podman Desktop on macOS)
        try:
            socket.getaddrinfo("host.docker.internal", None)
        except socket.gaierror:
            pass
        else:
            return "host.docker.internal"
    else:
        # Docker: try host.docker.internal first
        try:
            socket.getaddrinfo("host.docker.internal", None)
        except socket.gaierror:
            pass
        else:
            return "host.docker.internal"

        # Fallback to host.containers.internal (unlikely but possible)
        try:
            socket.getaddrinfo("host.containers.internal", None)
        except socket.gaierror:
            pass
        else:
            return "host.containers.internal"

    # Fallback: try to get gateway IP from routing table (Linux containers)
    try:
        with Path("/proc/net/route").open() as f:
            for line in f:
                fields = line.strip().split()
                min_field_count = 3  # Minimum fields needed: interface, destination, gateway
                if len(fields) >= min_field_count and fields[1] == "00000000":  # Default route
                    # Gateway is in hex format (little-endian)
                    gateway_hex = fields[2]
                    # Convert hex to IP address
                    # The hex is in little-endian format, so we read it backwards in pairs
                    octets = [gateway_hex[i : i + 2] for i in range(0, 8, 2)]
                    return ".".join(str(int(octet, 16)) for octet in reversed(octets))
    except (FileNotFoundError, PermissionError, IndexError, ValueError):
        pass

    return None


def transform_localhost_url(url: str) -> str:
    """Transform localhost URLs to container-accessible hosts when running in a container.

    Automatically detects if running inside a container and finds the appropriate host
    address to replace localhost/127.0.0.1. Tries in order:
    - host.docker.internal (if resolvable)
    - host.containers.internal (if resolvable)
    - Gateway IP from routing table (fallback)

    Args:
        url: The original URL

    Returns:
        Transformed URL with container-accessible host if applicable, otherwise the original URL.

    Example:
        >>> transform_localhost_url("http://localhost:5001")
        # Returns "http://host.docker.internal:5001" if running in Docker and hostname resolves
        # Returns "http://172.17.0.1:5001" if running in Docker on Linux (gateway IP fallback)
        # Returns "http://localhost:5001" if not in a container
    """
    container_host = get_container_host()

    if not container_host:
        return url

    # Replace localhost and 127.0.0.1 with the container host
    localhost_patterns = ["localhost", "127.0.0.1"]

    for pattern in localhost_patterns:
        if pattern in url:
            return url.replace(pattern, container_host)

    return url
