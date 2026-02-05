"""Startup prerequisites and health checks - ported from run_openrag_with_prereqs.sh

All actions require explicit user consent via Y/n prompts.
"""

import subprocess
import shutil
import platform
import time
import re
import os
from typing import Tuple, Optional
from pathlib import Path

MIN_PODMAN_MEMORY_MB = 8192  # 8 GB minimum


# =============================================================================
# Helpers
# =============================================================================

def say(msg: str) -> None:
    """Print a message."""
    print(f">>> {msg}")


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    """Ask yes/no question. Returns True for yes, False for no."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
        if not ans:
            return default_yes
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def ask_choice(prompt: str, options: list[str]) -> Optional[int]:
    """Ask user to choose from numbered options. Returns 1-based index or None."""
    print(prompt)
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    try:
        choice = input("Choice: ").strip()
        idx = int(choice)
        if 1 <= idx <= len(options):
            return idx
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return None


def has_cmd(cmd: str) -> bool:
    """Check if a command exists."""
    return shutil.which(cmd) is not None


def get_platform() -> str:
    """Get platform: 'macOS', 'Linux', 'WSL', or 'Windows'."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    elif system == "Linux":
        # Check for WSL
        try:
            with open("/proc/version", "r") as f:
                if "microsoft" in f.read().lower():
                    return "WSL"
        except:
            pass
        return "Linux"
    elif system == "Windows":
        return "Windows"
    return "Unknown"


def docker_is_podman() -> bool:
    """Check if 'docker' command is actually podman (alias/shim)."""
    if not has_cmd("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=5
        )
        if "podman" in result.stdout.lower():
            return True
        # Check symlink target
        docker_path = shutil.which("docker")
        if docker_path:
            real_path = os.path.realpath(docker_path)
            if "podman" in real_path.lower():
                return True
    except Exception:
        pass
    return False


# =============================================================================
# Runtime Detection
# =============================================================================

def docker_daemon_ready() -> bool:
    """Check if Docker daemon is running and accessible."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except:
        return False


def podman_ready() -> bool:
    """Check if Podman is ready (on macOS, machine must be running)."""
    try:
        result = subprocess.run(
            ["podman", "info"], capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except:
        return False


def compose_available() -> bool:
    """Check if docker compose or docker-compose is available."""
    # Try docker compose (v2)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"], capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return True
    except:
        pass
    # Try docker-compose (v1)
    return has_cmd("docker-compose")


# =============================================================================
# Installation (with user consent)
# =============================================================================

def install_homebrew() -> bool:
    """Install Homebrew on macOS. Returns True if successful."""
    if has_cmd("brew"):
        return True

    say("Homebrew not found (required to install Podman on macOS).")
    if not ask_yes_no("Install Homebrew?"):
        return False

    say("Installing Homebrew...")
    try:
        # Pipe installer script to bash - let user see progress interactively
        subprocess.run(
            ["sh", "-c", "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh | bash"],
            check=True
        )
        # Add to PATH for this session
        if Path("/opt/homebrew/bin/brew").exists():
            os.environ["PATH"] = f"/opt/homebrew/bin:{os.environ['PATH']}"
        elif Path("/usr/local/bin/brew").exists():
            os.environ["PATH"] = f"/usr/local/bin:{os.environ['PATH']}"
        return True
    except Exception as e:
        say(f"Failed to install Homebrew: {e}")
        return False


def install_podman() -> bool:
    """Install Podman CLI (not Desktop). Returns True if successful."""
    if has_cmd("podman"):
        say(f"Podman already installed: {shutil.which('podman')}")
        return True

    plat = get_platform()
    say("Podman CLI not found.")
    if not ask_yes_no("Install Podman?"):
        return False

    if plat == "macOS":
        if not install_homebrew():
            say("Cannot install Podman without Homebrew.")
            return False
        say("Installing Podman via Homebrew...")
        try:
            subprocess.run(["brew", "install", "podman"], check=True)
            return True
        except Exception as e:
            say(f"Failed: {e}")
            return False

    elif plat in ("Linux", "WSL"):
        say("Installing Podman via package manager (may prompt for sudo password)...")
        try:
            if has_cmd("apt-get"):
                # Don't capture output - let user see progress and type sudo password
                subprocess.run(["sudo", "apt-get", "update", "-y"], check=True)
                subprocess.run(["sudo", "apt-get", "install", "-y", "podman"], check=True)
            elif has_cmd("dnf"):
                subprocess.run(["sudo", "dnf", "install", "-y", "podman"], check=True)
            elif has_cmd("yum"):
                subprocess.run(["sudo", "yum", "install", "-y", "podman"], check=True)
            elif has_cmd("pacman"):
                subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm", "podman"], check=True)
            else:
                say("Unknown package manager. Please install podman manually.")
                return False
            return True
        except Exception as e:
            say(f"Failed: {e}")
            return False

    return False


def install_docker_linux() -> bool:
    """Install Docker Engine on Linux (not Docker Desktop). Returns True if successful."""
    if has_cmd("docker"):
        say(f"Docker already installed: {shutil.which('docker')}")
        return True

    say("Docker not found.")
    if not ask_yes_no("Install Docker Engine?"):
        return False

    say("Installing Docker via get.docker.com (may prompt for sudo password)...")
    try:
        # Don't capture output - let user see progress and type sudo password
        subprocess.run(
            ["sh", "-c", "curl -fsSL https://get.docker.com | sudo sh"],
            check=True
        )
        # Add user to docker group
        try:
            subprocess.run(["sudo", "usermod", "-aG", "docker", os.environ["USER"]], check=True)
            say("Added user to docker group. You may need to log out and back in.")
        except:
            pass
        return True
    except Exception as e:
        say(f"Failed: {e}")
        return False


# =============================================================================
# Runtime Setup (with user consent)
# =============================================================================

def start_docker_daemon() -> bool:
    """Start Docker daemon. Returns True if successful."""
    if docker_daemon_ready():
        return True

    say("Docker daemon is not running.")
    if not ask_yes_no("Start Docker?"):
        return False

    plat = get_platform()
    if plat == "macOS":
        say("Starting Docker Desktop...")
        subprocess.run(["open", "-gj", "-a", "Docker"], capture_output=True)
    else:
        say("Starting Docker service (may prompt for sudo password)...")
        # Don't capture output - let user type sudo password
        subprocess.run(["sudo", "systemctl", "start", "docker"])

    # Wait for daemon
    say("Waiting for Docker daemon...")
    for _ in range(30):
        if docker_daemon_ready():
            say("Docker daemon is ready.")
            return True
        time.sleep(2)

    say("Docker daemon did not start in time.")
    return False


def setup_podman_machine() -> bool:
    """Initialize and start Podman machine on macOS. Returns True if ready."""
    if get_platform() != "macOS":
        return podman_ready()

    # Check if machine exists
    try:
        result = subprocess.run(
            ["podman", "machine", "list", "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=10
        )
        machine_exists = bool(result.stdout.strip())
    except:
        machine_exists = False

    if not machine_exists:
        say("Podman machine does not exist.")
        if not ask_yes_no(f"Initialize Podman machine with {MIN_PODMAN_MEMORY_MB}MB memory?"):
            return False

        say("Initializing Podman machine...")
        try:
            subprocess.run([
                "podman", "machine", "init",
                "--memory", str(MIN_PODMAN_MEMORY_MB),
                "--rootful"
            ], check=True)
        except Exception as e:
            say(f"Failed to init machine: {e}")
            return False

    # Check if machine is running
    if not podman_ready():
        say("Podman machine is not running.")
        if not ask_yes_no("Start Podman machine?"):
            return False

        say("Starting Podman machine...")
        try:
            subprocess.run(["podman", "machine", "start"], check=True)
            # Wait for it
            for _ in range(15):
                if podman_ready():
                    say("Podman machine is ready.")
                    return True
                time.sleep(2)
        except Exception as e:
            say(f"Failed to start machine: {e}")
            return False

    return podman_ready()


def check_podman_machine_memory() -> Tuple[bool, int]:
    """Check Podman machine memory. Returns (is_sufficient, current_mb)."""
    if get_platform() != "macOS":
        return True, 0

    try:
        result = subprocess.run(
            ["podman", "machine", "inspect", "podman-machine-default",
             "--format", "{{.Resources.Memory}}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            current_mb = int(result.stdout.strip())
            return current_mb >= MIN_PODMAN_MEMORY_MB, current_mb
    except:
        pass
    return True, 0


def fix_podman_memory(version: str) -> bool:
    """Recreate Podman machine with more memory."""
    say(f"Podman machine has insufficient memory.")
    if not ask_yes_no(f"Recreate machine with {MIN_PODMAN_MEMORY_MB}MB? (WARNING: deletes containers/images)"):
        return False

    major = int(version.split(".")[0]) if version and version[0].isdigit() else 0

    if major >= 5:
        say("Resetting Podman machine...")
        result = subprocess.run(
            ["podman", "machine", "reset", "-f"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            # Re-init with proper memory
            subprocess.run([
                "podman", "machine", "init",
                "--memory", str(MIN_PODMAN_MEMORY_MB),
                "--rootful"
            ], capture_output=True)
            subprocess.run(["podman", "machine", "start"], capture_output=True)
            say("Done.")
            return True

    # Fallback: manual reset
    say("Manual reset: stop -> rm -> init -> start...")
    subprocess.run(["podman", "machine", "stop"], capture_output=True)
    subprocess.run(["podman", "machine", "rm", "-f"], capture_output=True)
    subprocess.run([
        "podman", "machine", "init",
        "--memory", str(MIN_PODMAN_MEMORY_MB),
        "--rootful"
    ], capture_output=True)
    subprocess.run(["podman", "machine", "start"], capture_output=True)
    say("Done.")
    return True


# =============================================================================
# Health Checks
# =============================================================================

def check_runtime_conflict() -> Tuple[bool, Optional[str]]:
    """Check if both Docker and Podman are running independently."""
    if docker_is_podman():
        return False, None  # docker is alias for podman, no conflict

    docker_running = docker_daemon_ready()
    podman_running = podman_ready()

    if docker_running and podman_running:
        return True, "Both Docker and Podman are running"
    return False, None


def check_storage_corruption(runtime: str) -> Tuple[bool, Optional[str]]:
    """Check for storage/overlay corruption."""
    cmd = ["podman", "info"] if runtime == "podman" else ["docker", "info"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        stderr = result.stderr

        corruption_patterns = [
            r"graph driver info.*invalid argument",
            r"readlink.*storage.*invalid argument",
            r"layer not known",
            r"overlay.*mount.*invalid",
            r"storage.*corrupt",
        ]
        for pattern in corruption_patterns:
            if re.search(pattern, stderr, re.IGNORECASE):
                return True, stderr
    except:
        pass
    return False, None


def fix_storage_corruption(runtime: str, version: str) -> bool:
    """Reset storage to fix corruption."""
    say("Storage corruption detected.")
    if not ask_yes_no(f"Reset {runtime} storage? (WARNING: deletes all containers/images)"):
        return False

    if runtime == "podman":
        major = int(version.split(".")[0]) if version and version[0].isdigit() else 0
        if major >= 5:
            say("Resetting Podman machine...")
            result = subprocess.run(
                ["podman", "machine", "reset", "-f"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                say("Reset complete.")
                return True

        # Fallback
        say("Manual reset...")
        subprocess.run(["podman", "machine", "stop"], capture_output=True)
        subprocess.run(["podman", "machine", "rm", "-f"], capture_output=True)
        subprocess.run([
            "podman", "machine", "init",
            "--memory", str(MIN_PODMAN_MEMORY_MB),
            "--rootful"
        ], capture_output=True)
        subprocess.run(["podman", "machine", "start"], capture_output=True)
        say("Done.")
        return True
    else:
        say("Pruning Docker system...")
        subprocess.run(["docker", "system", "prune", "-af"], capture_output=True)
        say("Done.")
        return True


def fix_runtime_conflict() -> Optional[str]:
    """Handle runtime conflict. Returns chosen runtime or None to exit."""
    say("Both Docker and Podman are running simultaneously.")
    say("This can cause socket conflicts.")
    print()

    choice = ask_choice("Choose which runtime to use:", [
        "Stop Docker, use Podman",
        "Stop Podman, use Docker",
        "Continue anyway (not recommended)",
        "Exit"
    ])

    if choice == 1:
        say("Stopping Docker...")
        subprocess.run(["pkill", "-f", "Docker"], capture_output=True)
        time.sleep(2)
        return "podman"
    elif choice == 2:
        say("Stopping Podman machine...")
        subprocess.run(["podman", "machine", "stop"], capture_output=True)
        return "docker"
    elif choice == 3:
        return "continue"
    else:
        return None


# =============================================================================
# Main Entry Point
# =============================================================================

def run_startup_checks() -> bool:
    """
    Run all startup prerequisites and health checks.
    Returns True if OK to proceed, False to exit.

    All actions require explicit user consent.
    """
    plat = get_platform()
    print()
    say(f"Platform: {plat}")
    print("-" * 40)

    # 1. Check if we have any runtime
    has_docker = has_cmd("docker") and not docker_is_podman()
    has_podman = has_cmd("podman")

    if not has_docker and not has_podman:
        say("No container runtime found.")
        print()
        choice = ask_choice("Choose a container runtime to install:", [
            "Podman (recommended)",
            "Docker" if plat in ("Linux", "WSL") else "Docker (manual install required on macOS)",
            "Exit"
        ])

        if choice == 1:
            if not install_podman():
                return False
            has_podman = True
        elif choice == 2:
            if plat == "macOS":
                say("Please install Docker Desktop manually from: https://docker.com/products/docker-desktop")
                say("Then restart OpenRAG.")
                return False
            else:
                if not install_docker_linux():
                    return False
                has_docker = True
        else:
            return False

    # 2. Check for runtime conflict
    if has_docker and has_podman:
        has_conflict, _ = check_runtime_conflict()
        if has_conflict:
            result = fix_runtime_conflict()
            if result is None:
                return False

    # 3. Determine which runtime to use
    runtime = "podman" if (has_podman and (docker_is_podman() or not has_docker)) else "docker"
    runtime_version = ""

    # Get version
    try:
        cmd = ["podman", "--version"] if runtime == "podman" else ["docker", "--version"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        # Extract version number (e.g., "podman version 5.7.1" -> "5.7.1")
        match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
        if match:
            runtime_version = match.group(1)
    except:
        pass

    say(f"Using {runtime}" + (f" {runtime_version}" if runtime_version else ""))

    # 4. Setup runtime
    if runtime == "podman":
        if not setup_podman_machine():
            say("Podman is not ready. Cannot proceed.")
            return False

        # Check memory
        mem_ok, current_mb = check_podman_machine_memory()
        if not mem_ok and current_mb > 0:
            say(f"Podman machine has {current_mb}MB memory ({MIN_PODMAN_MEMORY_MB}MB recommended).")
            fix_podman_memory(runtime_version)
    else:
        if not start_docker_daemon():
            say("Docker is not ready. Cannot proceed.")
            return False

    # 5. Check for storage corruption
    is_corrupted, error_msg = check_storage_corruption(runtime)
    if is_corrupted:
        say("Storage corruption detected!")
        if error_msg:
            print(f"   {error_msg[:200]}...")
        if not fix_storage_corruption(runtime, runtime_version):
            # User declined fix, but continue anyway
            pass

    # 6. Check compose
    if not compose_available():
        say("Docker Compose not found.")
        say("OpenRAG requires docker-compose or 'docker compose'.")
        if runtime == "podman":
            say("Podman typically includes compose. Try: podman compose version")
        else:
            say("Install docker-compose-plugin via your package manager.")

    print("-" * 40)
    say("Prerequisites check complete.")
    print()
    return True
