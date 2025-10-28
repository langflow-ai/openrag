"""Main TUI application for OpenRAG."""

import sys
from pathlib import Path
from typing import Iterable, Optional
from textual.app import App, ComposeResult
from utils.logging_config import get_logger
try:
    from importlib.resources import files
except ImportError:
    from importlib_resources import files

logger = get_logger(__name__)

from .screens.welcome import WelcomeScreen
from .screens.config import ConfigScreen
from .screens.monitor import MonitorScreen
from .screens.logs import LogsScreen
from .screens.diagnostics import DiagnosticsScreen
from .managers.env_manager import EnvManager
from .managers.container_manager import ContainerManager
from .managers.docling_manager import DoclingManager
from .utils.platform import PlatformDetector
from .widgets.diagnostics_notification import notify_with_diagnostics


class OpenRAGTUI(App):
    """OpenRAG Terminal User Interface application."""

    TITLE = "OpenRAG TUI"
    SUB_TITLE = "Container Management & Configuration"

    CSS = """
    Screen {
        background: #27272a;
    }

    #main-container {
        height: 100%;
        padding: 1;
    }

    #welcome-container {
        align: center middle;
        width: 100%;
        height: 100%;
    }

    #welcome-text {
        text-align: center;
        margin-bottom: 2;
    }

    .button-row {
        align: center middle;
        height: auto;
        margin: 1 0;
    }

    .button-row Button {
        margin: 0 1;
        min-width: 20;
        border: solid #3f3f46;
    }
    
    #config-header {
        text-align: center;
        margin-bottom: 2;
    }
    
    #config-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    
    #config-form {
        width: 80%;
        max-width: 100;
        margin: 0;
        padding: 1;
        height: auto;
    }
    
    #config-form Input {
        margin-bottom: 1;
        width: 100%;
    }

    /* Actions under Documents Paths input */
    #docs-path-actions {
        width: 100%;
        padding-left: 0;
        margin-top: -1;
        height: auto;
    }
    #docs-path-actions Button {
        width: auto;
        min-width: 12;
    }
    
    #config-form Label {
        margin-bottom: 0;
        padding-left: 1;
    }

    .helper-text {
        margin: 0 0 1 1;
    }

    /* Password field label rows */
    #config-form Horizontal {
        height: auto;
        align: left middle;
        margin-bottom: 0;
    }

    #config-form Horizontal Label {
        width: auto;
        margin-right: 1;
    }

    /* Password input rows */
    #opensearch-password-row,
    #langflow-password-row {
        width: 100%;
        height: auto;
        align: left middle;
    }

    #opensearch-password-row Input,
    #langflow-password-row Input {
        width: 1fr;
    }

    /* Password toggle buttons */
    #toggle-opensearch-password,
    #toggle-langflow-password {
        min-width: 8;
        width: 8;
        height: 3;
        padding: 0 1;
        margin-left: 1;
    }

    /* Docs path actions row */
    
    #services-content {
        height: 100%;
    }
    
    #runtime-status {
        background: $panel;
        border: solid $primary;
        padding: 1;
        margin-bottom: 1;
    }
    
    #services-table {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
    }

    #images-table {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }

    
    
    #logs-scroll {
        height: 1fr;
        border: solid $primary;
        background: $surface;
    }
    
    .controls-row {
        align: left middle;
        height: auto;
        margin: 1 0;
    }
    
    .controls-row > * {
        margin-right: 1;
    }
    
    .label {
        width: auto;
        margin-right: 1;
        text-style: bold;
    }
    
    #system-info {
        background: $panel;
        border: solid $primary;
        padding: 2;
        height: 1fr;
    }
    
    TabbedContent {
        height: 1fr;
    }
    
    TabPane {
        padding: 1;
        height: 1fr;
    }
    
    .tab-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    TabPane ScrollableContainer {
        height: 100%;
        padding: 1;
    }

    /* Modern dark theme with pink accents */
    Static {
        color: #fafafa;
    }

    Button,
    Button.-default,
    Button.-primary,
    Button.-success,
    Button.-warning,
    Button.-error {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #52525b !important;
        text-style: none !important;
        tint: transparent 0% !important;
    }

    Button > *,
    Button.-default > *,
    Button.-primary > *,
    Button.-success > *,
    Button.-warning > *,
    Button.-error > * {
        background: transparent !important;
        color: #fafafa !important;
        text-style: none !important;
    }

    Button:hover,
    Button.-default:hover,
    Button.-primary:hover,
    Button.-success:hover,
    Button.-warning:hover,
    Button.-error:hover {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #52525b !important;
    }

    Button:focus,
    Button:focus-within,
    Button.-active,
    Button.-default:focus,
    Button.-default:focus-within,
    Button.-default.-active,
    Button.-primary:focus,
    Button.-primary:focus-within,
    Button.-primary.-active,
    Button.-success:focus,
    Button.-success:focus-within,
    Button.-success.-active,
    Button.-warning:focus,
    Button.-warning:focus-within,
    Button.-warning.-active,
    Button.-error:focus,
    Button.-error:focus-within,
    Button.-error.-active {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #ec4899 !important;
    }

    DataTable {
        background: #27272a;
        color: #fafafa;
    }

    DataTable > .datatable--header {
        background: #3f3f46;
        color: #fafafa;
    }

    DataTable > .datatable--cursor {
        background: #52525b;
    }

    Input {
        background: #18181b;
        color: #fafafa;
        border: solid #3f3f46;
    }

    Input:focus {
        border: solid #ec4899;
    }

    Label {
        color: #fafafa;
    }

    Checkbox {
        background: transparent;
        color: #fafafa;
        border: none;
        padding: 0;
        margin-left: 2;
    }

    Checkbox > Static {
        background: transparent;
        color: #fafafa;
    }

    Header {
        background: #27272a;
        color: #fafafa;
    }

    Footer {
        background: #27272a;
        color: #a1a1aa;
    }

    #runtime-status {
        background: #27272a;
        border: solid #3f3f46;
        color: #fafafa;
    }

    #system-info {
        background: #27272a;
        border: solid #3f3f46;
        color: #fafafa;
    }

    #services-table, #images-table {
        background: #27272a;
    }

    * {
        scrollbar-background: #27272a;
        scrollbar-background-hover: #3f3f46;
        scrollbar-background-active: #3f3f46;
        scrollbar-color: #52525b;
        scrollbar-color-hover: #71717a;
        scrollbar-color-active: #71717a;
        scrollbar-corner-color: #27272a;
    }
    """

    def __init__(self):
        super().__init__()
        self.platform_detector = PlatformDetector()
        self.container_manager = ContainerManager()
        self.env_manager = EnvManager()
        self.docling_manager = DoclingManager()  # Initialize singleton instance

    def on_mount(self) -> None:
        """Initialize the application."""
        # Check for runtime availability and show appropriate screen
        if not self.container_manager.is_available():
            notify_with_diagnostics(
                self,
                "No container runtime found. Please install Docker or Podman.",
                severity="warning",
                timeout=10,
            )

        # Load existing config if available
        config_exists = self.env_manager.load_existing_env()

        # Start with welcome screen
        self.push_screen(WelcomeScreen())

    async def action_quit(self) -> None:
        """Quit the application."""
        # Cleanup docling manager before exiting
        self.docling_manager.cleanup()
        self.exit()

    def check_runtime_requirements(self) -> tuple[bool, str]:
        """Check if runtime requirements are met."""
        if not self.container_manager.is_available():
            return False, self.platform_detector.get_installation_instructions()

        # Check Podman macOS memory if applicable
        runtime_info = self.container_manager.get_runtime_info()
        if runtime_info.runtime_type.value == "podman":
            is_sufficient, _, message = (
                self.platform_detector.check_podman_macos_memory()
            )
            if not is_sufficient:
                return False, f"Podman VM memory insufficient:\n{message}"

        return True, "Runtime requirements satisfied"


def _copy_assets(resource_tree, destination: Path, allowed_suffixes: Optional[Iterable[str]] = None, *, force: bool = False) -> None:
    """Copy packaged assets into destination and optionally overwrite existing files.

    When ``force`` is True, files are refreshed if the packaged bytes differ.
    """
    destination.mkdir(parents=True, exist_ok=True)

    for resource in resource_tree.iterdir():
        target_path = destination / resource.name

        if resource.is_dir():
            _copy_assets(resource, target_path, allowed_suffixes, force=force)
            continue

        if allowed_suffixes and not any(resource.name.endswith(suffix) for suffix in allowed_suffixes):
            continue
        resource_bytes = resource.read_bytes()

        if target_path.exists():
            if not force:
                continue

            try:
                if target_path.read_bytes() == resource_bytes:
                    continue
            except Exception as read_error:
                logger.debug(f"Failed to read existing asset {target_path}: {read_error}")

        target_path.write_bytes(resource_bytes)
        logger.info(f"Copied bundled asset: {target_path}")


def copy_sample_documents(*, force: bool = False) -> None:
    """Copy sample documents from package to current directory if they don't exist."""
    documents_dir = Path("documents")

    try:
        assets_files = files("tui._assets.documents")
        _copy_assets(assets_files, documents_dir, allowed_suffixes=(".pdf",), force=force)
    except Exception as e:
        logger.debug(f"Could not copy sample documents: {e}")
        # This is not a critical error - the app can work without sample documents


def copy_sample_flows(*, force: bool = False) -> None:
    """Copy sample flows from package to current directory if they don't exist."""
    flows_dir = Path("flows")

    try:
        assets_files = files("tui._assets.flows")
        _copy_assets(assets_files, flows_dir, allowed_suffixes=(".json",), force=force)
    except Exception as e:
        logger.debug(f"Could not copy sample flows: {e}")
        # The app can proceed without bundled flows


def copy_compose_files(*, force: bool = False) -> None:
    """Copy docker-compose templates into the workspace if they are missing."""
    try:
        assets_root = files("tui._assets")
    except Exception as e:
        logger.debug(f"Could not access compose assets: {e}")
        return

    for filename in ("docker-compose.yml", "docker-compose-cpu.yml"):
        destination = Path(filename)
        if destination.exists() and not force:
            continue

        try:
            resource = assets_root.joinpath(filename)
            if not resource.is_file():
                logger.debug(f"Compose template not found in assets: {filename}")
                continue

            resource_bytes = resource.read_bytes()
            if destination.exists():
                try:
                    if destination.read_bytes() == resource_bytes:
                        continue
                except Exception as read_error:
                    logger.debug(f"Failed to read existing compose file {destination}: {read_error}")

            destination.write_bytes(resource_bytes)
            logger.info(f"Copied docker-compose template: {filename}")
        except Exception as error:
            logger.debug(f"Could not copy compose file {filename}: {error}")


def run_tui():
    """Run the OpenRAG TUI application."""
    # Check for native Windows before launching TUI
    from .utils.platform import PlatformDetector
    platform_detector = PlatformDetector()

    if platform_detector.is_native_windows():
        print("\n" + "=" * 60)
        print("⚠️  Native Windows Not Supported")
        print("=" * 60)
        print(platform_detector.get_wsl_recommendation())
        print("=" * 60 + "\n")
        sys.exit(1)

    app = None
    try:
        # Keep bundled assets aligned with the packaged versions
        copy_sample_documents(force=True)
        copy_sample_flows(force=True)
        copy_compose_files(force=True)

        app = OpenRAGTUI()
        app.run()
    except KeyboardInterrupt:
        logger.info("OpenRAG TUI interrupted by user")
    except Exception as e:
        logger.error("Error running OpenRAG TUI", error=str(e))
    finally:
        # Ensure cleanup happens even on exceptions
        if app and hasattr(app, 'docling_manager'):
            app.docling_manager.cleanup()
        sys.exit(0)


if __name__ == "__main__":
    run_tui()
