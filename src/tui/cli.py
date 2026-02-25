"""CLI interactive walkthrough for OpenRAG."""

import asyncio
import getpass
import os
import signal
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from . import __version__
from .config_fields import CONFIG_SECTIONS
from .managers.container_manager import ContainerManager, ServiceStatus
from .managers.docling_manager import DoclingManager
from .managers.env_manager import EnvManager
from .utils.platform import PlatformDetector

console = Console()

BANNER = """\
 ██████╗ ██████╗ ███████╗███╗   ██╗██████╗  █████╗  ██████╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔══██╗██╔════╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██████╔╝███████║██║  ███╗
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██╗██╔══██║██║   ██║
╚██████╔╝██║     ███████╗██║ ╚████║██║  ██║██║  ██║╚██████╔╝
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝"""


def run_cli():
    """Top-level CLI entry point: bootstrap, banner, route to menu or walkthrough."""
    from .main import (
        copy_compose_files,
        copy_sample_documents,
        copy_sample_flows,
        migrate_legacy_data_directories,
        setup_host_directories,
    )

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        migrate_legacy_data_directories()
        setup_host_directories()
        copy_sample_documents(force=True)
        copy_sample_flows(force=True)
        copy_compose_files(force=True)
    except Exception:
        pass  # Non-critical bootstrap errors

    env_manager = EnvManager()
    container_manager = ContainerManager()
    docling_manager = DoclingManager()

    _print_banner(container_manager)

    if env_manager.env_file.exists():
        env_manager.load_existing_env()
        _existing_config_menu(env_manager, container_manager, docling_manager)
    else:
        _setup_walkthrough(env_manager, container_manager, docling_manager)


def _handle_sigint(sig, frame):
    """Handle Ctrl+C for clean exit."""
    console.print("\n\nExiting.", style="dim")
    sys.exit(0)


def _print_banner(container_manager: ContainerManager):
    """Print ASCII art banner with version and runtime info."""
    console.print(BANNER, style="bold white")
    console.print(f"v{__version__}", style="white")
    console.print()

    runtime_info = container_manager.get_runtime_info()
    runtime_type = runtime_info.runtime_type.value
    if runtime_type == "none":
        console.print("[yellow]No container runtime detected[/yellow]")
    else:
        version = runtime_info.version or ""
        label = runtime_type.replace("-", " ").title()
        if version:
            console.print(f"Using {label} ({runtime_type} version {version})")
        else:
            console.print(f"Using {label}")
    console.print()


def _get_service_states(
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
) -> tuple[dict, dict, bool]:
    """Fetch container and docling statuses in one shot.

    Returns (container_services, docling_status, all_running).
    """
    async def _inner():
        if container_manager.is_available():
            return await container_manager.get_service_status(force_refresh=True)
        return {}

    try:
        container_services = asyncio.run(_inner())
    except Exception:
        container_services = {}

    docling_status = docling_manager.get_status()

    # Determine if everything is up
    expected = set(container_manager.expected_services)
    running = {
        name for name, info in container_services.items()
        if info.status == ServiceStatus.RUNNING
    }
    containers_up = running == expected and len(expected) > 0
    docling_up = docling_status.get("status") == "running"
    all_running = containers_up and docling_up

    return container_services, docling_status, all_running


def _existing_config_menu(
    env_manager: EnvManager,
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
):
    """Numbered menu for returning users with existing .env."""
    console.print("Existing configuration found.", style="bold")
    console.print()

    while True:
        _, _, running = _get_service_states(container_manager, docling_manager)

        # Build menu options dynamically based on service state
        options: list[tuple[str, str]] = []
        if running:
            console.print("  [green]✓ Services are running[/green]")
            console.print()
            options.append(("open", "Open OpenRAG in browser"))
            options.append(("stop", "Stop services"))
        else:
            options.append(("start", "Start services"))
        options.append(("reconfig", "Reconfigure"))
        options.append(("status", "Show status"))
        options.append(("exit", "Exit"))

        for i, (_, label) in enumerate(options, 1):
            console.print(f"  [{i}] {label}")
        console.print()

        max_choice = len(options)
        try:
            choice = input(f"Choose [1-{max_choice}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting.", style="dim")
            break

        try:
            idx = int(choice) - 1
        except ValueError:
            console.print("Invalid choice, try again.", style="red")
            console.print()
            continue

        if idx < 0 or idx >= len(options):
            console.print("Invalid choice, try again.", style="red")
            console.print()
            continue

        action = options[idx][0]
        if action == "start":
            _start_services_cli(container_manager, docling_manager)
        elif action == "stop":
            _stop_services_cli(container_manager, docling_manager)
        elif action == "open":
            frontend_url = f"http://localhost:{os.getenv('FRONTEND_PORT', '3000')}"
            console.print(f"Opening {frontend_url} ...")
            try:
                webbrowser.open(frontend_url)
            except Exception:
                pass
            break
        elif action == "reconfig":
            _setup_walkthrough(env_manager, container_manager, docling_manager)
        elif action == "status":
            _show_status_cli(container_manager, docling_manager)
        elif action == "exit":
            break

        console.print()


def _setup_walkthrough(
    env_manager: EnvManager,
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
):
    """Orchestrate: collect config → save → optionally start services."""
    _collect_config(env_manager, advanced=False)

    try:
        configure_advanced = input("Configure cloud connectors & advanced settings? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        configure_advanced = "n"

    if configure_advanced == "y":
        _collect_config(env_manager, advanced=True, advanced_only=True)

    if not _validate_and_save(env_manager):
        return

    console.print()
    try:
        start_now = input("Start services now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        start_now = "n"

    if start_now != "n":
        # Stop any running services first so they pick up the new config
        _, _, already_running = _get_service_states(container_manager, docling_manager)
        if already_running:
            _stop_services_cli(container_manager, docling_manager)
        _start_services_cli(container_manager, docling_manager)

        console.print()
        frontend_url = f"http://localhost:{os.getenv('FRONTEND_PORT', '3000')}"
        console.print(f"[bold green]OpenRAG is running at {frontend_url}[/bold green]")
        try:
            webbrowser.open(frontend_url)
        except Exception:
            pass


def _collect_config(
    env_manager: EnvManager,
    advanced: bool = False,
    advanced_only: bool = False,
):
    """Collect config by iterating CONFIG_SECTIONS.

    Args:
        env_manager: The environment manager with config to populate.
        advanced: If True, include advanced sections/fields.
        advanced_only: If True, skip non-advanced sections (used for the
            second pass after user opts into advanced config).
    """
    config = env_manager.config

    for section in CONFIG_SECTIONS:
        # Skip advanced sections unless advanced mode is on
        if section.advanced and not advanced:
            continue
        # In advanced_only pass, skip non-advanced sections (already collected)
        if advanced_only and not section.advanced:
            # But still collect advanced fields within non-advanced sections
            has_advanced_fields = any(f.advanced for f in section.fields)
            if not has_advanced_fields:
                continue

        # Gate prompt for optional sections (e.g. "Configure Google OAuth? [y/N]")
        if section.gate_prompt:
            try:
                answer = input(f"{section.gate_prompt} [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print()
                answer = "n"
            if answer != "y":
                continue

        console.print(Rule(section.name))

        for field in section.fields:
            # Skip advanced fields unless advanced mode
            if field.advanced and not advanced:
                continue
            # In advanced_only pass within a non-advanced section, skip non-advanced fields
            if advanced_only and not section.advanced and not field.advanced:
                continue

            current = getattr(config, field.name, field.default) or ""

            # Prompt for the value
            if field.secret:
                value = _prompt_secret(
                    f"{field.label} ({field.helper_text})" if field.helper_text else field.label,
                    default=current,
                )
            else:
                value = _prompt_with_default(
                    field.label,
                    current or field.default,
                    secret=False,
                )

            # Special handling: password strength check for opensearch_password
            if field.name == "opensearch_password" and value:
                strength = _validate_password_strength(value)
                if strength is not None:
                    console.print(f"  {strength}")

            # Special handling: sync documents path
            if field.name == "openrag_documents_paths" and value:
                first_path = value.split(",")[0].strip()
                config.openrag_documents_path = first_path

            # Run validator and warn (but don't block)
            if value and field.validator and not field.validator(value):
                console.print(f"  [yellow]Warning: {field.validator_error}[/yellow]")

            setattr(config, field.name, value)


def _validate_and_save(env_manager: EnvManager) -> bool:
    """Validate config and save .env file."""
    env_manager.setup_secure_defaults()

    if not env_manager.validate_config():
        console.print()
        console.print("[red]Configuration errors:[/red]")
        for field_name, error in env_manager.config.validation_errors.items():
            console.print(f"  [red]• {field_name}: {error}[/red]")
        return False

    success = env_manager.save_env_file()
    if success:
        console.print(f"\n[green]✓ Configuration saved to {env_manager.env_file}[/green]")
    else:
        console.print("\n[red]✗ Failed to save configuration[/red]")
    return success


def _start_services_cli(
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
):
    """Start container services and docling via async bridge."""
    console.print()
    console.print("Starting OpenRAG services...", style="bold")

    async def _inner():
        # Start container services
        if container_manager.is_available():
            async for item in container_manager.start_services():
                # start_services yields (success, message) or (success, message, replace_last)
                success = item[0]
                message = item[1]
                replace_last = item[2] if len(item) > 2 else False
                if replace_last:
                    # Progress update — overwrite line
                    console.print(f"\r  {message}", end="")
                else:
                    console.print(f"  {message}")

                if not success and "error" in message.lower():
                    console.print(f"  [red]✗ {message}[/red]")
        else:
            console.print("  [yellow]No container runtime available[/yellow]")

        # Start docling
        if not docling_manager.is_running():
            success, message = await docling_manager.start()
            if success:
                console.print(f"  {message}")
            else:
                console.print(f"  [yellow]{message}[/yellow]")

    try:
        asyncio.run(_inner())
        console.print("[green]✓ All services started[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error starting services: {e}[/red]")


def _stop_services_cli(
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
):
    """Stop container services and docling via async bridge."""
    console.print()
    console.print("Stopping OpenRAG services...", style="bold")

    async def _inner():
        # Stop container services
        if container_manager.is_available():
            async for success, message, *rest in container_manager.stop_services():
                console.print(f"  {message}")
        # Stop docling
        if docling_manager.is_running():
            success, message = await docling_manager.stop()
            console.print(f"  {message}")

    try:
        asyncio.run(_inner())
        console.print("[green]✓ All services stopped[/green]")
    except Exception as e:
        console.print(f"[red]✗ Error stopping services: {e}[/red]")


def _show_status_cli(
    container_manager: ContainerManager,
    docling_manager: DoclingManager,
):
    """Show a rich table of all service statuses."""
    console.print()

    services, docling_status, _ = _get_service_states(container_manager, docling_manager)

    table = Table(title="Service Status")
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    table.add_column("Ports", style="dim")

    for name, info in services.items():
        status_str = info.status.value
        if info.status == ServiceStatus.RUNNING:
            style = "green"
        elif info.status == ServiceStatus.STOPPED:
            style = "red"
        elif info.status == ServiceStatus.STARTING:
            style = "yellow"
        else:
            style = "dim"
        ports = ", ".join(info.ports) if info.ports else ""
        table.add_row(name, f"[{style}]{status_str}[/{style}]", ports)

    # Docling status
    doc_state = docling_status.get("status", "unknown")
    if doc_state == "running":
        style = "green"
    elif doc_state == "stopped":
        style = "red"
    else:
        style = "yellow"
    doc_port = str(docling_status.get("port", ""))
    table.add_row("docling-serve", f"[{style}]{doc_state}[/{style}]", doc_port)

    console.print(table)


def _prompt_secret(prompt: str, default: str = "") -> str:
    """Prompt for a secret value using getpass (hides input)."""
    masked = _mask_value(default) if default else ""
    suffix = f" [{masked}]" if masked else ""
    try:
        value = getpass.getpass(f"  {prompt}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        console.print()
        return default
    return value if value else default


def _prompt_with_default(prompt: str, default: str = "", secret: bool = False) -> str:
    """Prompt for a value with an optional default shown."""
    if secret and default:
        display = _mask_value(default)
    else:
        display = default

    suffix = f" [{display}]" if display else ""

    try:
        if secret:
            value = getpass.getpass(f"  {prompt}{suffix}: ")
        else:
            value = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return default

    return value if value else default


def _mask_value(value: str) -> str:
    """Mask a secret value, showing first 4 and last 4 characters."""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _validate_password_strength(password: str) -> str | None:
    """Check password strength with zxcvbn. Returns a status string or None."""
    try:
        from zxcvbn import zxcvbn
    except ImportError:
        return None

    result = zxcvbn(password)
    score = result["score"]
    labels = ["very weak", "weak", "fair", "strong", "very strong"]
    label = labels[score]

    if score >= 3:
        return f"[green]✓ Password strength: {label}[/green]"

    feedback = result.get("feedback", {})
    warning = feedback.get("warning", "")
    suggestions = feedback.get("suggestions", [])
    hint = warning or (suggestions[0] if suggestions else "")
    msg = f"[yellow]⚠ Password strength: {label}[/yellow]"
    if hint:
        msg += f" — {hint}"
    return msg
