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


def guess_host_ip_for_containers(logger=None) -> str:
    """Best-effort detection of a host IP reachable from container networks.

    The logic mirrors what the TUI uses when launching docling-serve so that
    both CLI and API use consistent addresses. Preference order:
    1. Docker/Podman compose networks (ended with ``_default``)
    2. Networks with active containers
    3. Any discovered bridge or CNI gateway interfaces

    Args:
        logger: Optional logger to emit diagnostics; falls back to module logger.

    Returns:
        The most appropriate host IP address if discovered, otherwise ``"127.0.0.1"``.
    """
    import json
    import logging
    import re
    import shutil
    import socket
    import subprocess

    log = logger or logging.getLogger(__name__)

    def can_bind_to_address(ip_addr: str) -> bool:
        """Test if we can bind to the given IP address."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((ip_addr, 0))  # Port 0 = let OS choose a free port
                return True
        except (OSError, socket.error) as e:
            log.debug("Cannot bind to %s: %s", ip_addr, e)
            return False

    def run(cmd, timeout=2, text=True):
        return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout)

    gateways: list[str] = []
    compose_gateways: list[str] = []
    active_gateways: list[str] = []

    # ---- Docker networks
    if shutil.which("docker"):
        try:
            ls = run(["docker", "network", "ls", "--format", "{{.Name}}"])
            if ls.returncode == 0:
                for name in filter(None, ls.stdout.splitlines()):
                    try:
                        insp = run(["docker", "network", "inspect", name, "--format", "{{json .}}"])
                        if insp.returncode == 0 and insp.stdout.strip():
                            payload = insp.stdout.strip()
                            nw = json.loads(payload)[0] if payload.startswith("[") else json.loads(payload)
                            ipam = nw.get("IPAM", {})
                            containers = nw.get("Containers", {})
                            for cfg in ipam.get("Config", []) or []:
                                gw = cfg.get("Gateway")
                                if not gw:
                                    continue
                                if name.endswith("_default"):
                                    compose_gateways.append(gw)
                                elif len(containers) > 0:
                                    active_gateways.append(gw)
                                else:
                                    gateways.append(gw)
                    except Exception:
                        continue
        except Exception:
            pass

    # ---- Podman networks
    if shutil.which("podman"):
        try:
            ls = run(["podman", "network", "ls", "--format", "json"])
            if ls.returncode == 0 and ls.stdout.strip():
                for net in json.loads(ls.stdout):
                    name = net.get("name") or net.get("Name")
                    if not name:
                        continue
                    try:
                        insp = run(["podman", "network", "inspect", name, "--format", "json"])
                        if insp.returncode == 0 and insp.stdout.strip():
                            arr = json.loads(insp.stdout)
                            for item in (arr if isinstance(arr, list) else [arr]):
                                for sn in item.get("subnets", []) or []:
                                    gw = sn.get("gateway")
                                    if not gw:
                                        continue
                                    if name.endswith("_default") or "_" in name:
                                        compose_gateways.append(gw)
                                    else:
                                        gateways.append(gw)
                    except Exception:
                        continue
        except Exception:
            pass

    # ---- Host bridge interfaces
    if not gateways and not compose_gateways and not active_gateways:
        try:
            if shutil.which("ip"):
                show = run(["ip", "-o", "-4", "addr", "show"])
                if show.returncode == 0:
                    for line in show.stdout.splitlines():
                        match = re.search(r"^\d+:\s+([\w_.:-]+)\s+.*\binet\s+(\d+\.\d+\.\d+\.\d+)/", line)
                        if not match:
                            continue
                        ifname, ip_addr = match.group(1), match.group(2)
                        if ifname == "docker0" or ifname.startswith(("br-", "cni")):
                            gateways.append(ip_addr)
            elif shutil.which("ifconfig"):
                show = run(["ifconfig"])
                for block in show.stdout.split("\n\n"):
                    if any(block.strip().startswith(n) for n in ("docker0", "cni", "br-")):
                        match = re.search(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", block)
                        if match:
                            gateways.append(match.group(1))
        except Exception:
            pass

    seen: set[str] = set()
    ordered_candidates: list[str] = []

    for collection in (compose_gateways, active_gateways, gateways):
        for ip_addr in collection:
            if ip_addr not in seen:
                ordered_candidates.append(ip_addr)
                seen.add(ip_addr)

    if ordered_candidates:
        if len(ordered_candidates) > 1:
            log.info(
                "Container-reachable host IP candidates: %s",
                ", ".join(ordered_candidates),
            )

        # Try each candidate and return the first one we can bind to
        for ip_addr in ordered_candidates:
            if can_bind_to_address(ip_addr):
                if len(ordered_candidates) > 1:
                    log.info("Selected bindable host IP: %s", ip_addr)
                else:
                    log.info("Container-reachable host IP: %s", ip_addr)
                return ip_addr
            log.debug("Skipping %s (cannot bind)", ip_addr)

        # None of the candidates were bindable, fall back to 127.0.0.1
        log.warning(
            "None of the discovered IPs (%s) can be bound; falling back to 127.0.0.1",
            ", ".join(ordered_candidates),
        )
        return "127.0.0.1"

    log.warning(
        "No container bridge IP found. For rootless Podman (slirp4netns) there may be no host bridge; publish ports or use 10.0.2.2 from the container."
    )

    return "127.0.0.1"
