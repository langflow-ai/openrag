"""Main TUI application for OpenRAG."""

import sys
from pathlib import Path
from textual.app import App, ComposeResult
from utils.logging_config import get_logger

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
        background: #0f172a;
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

    /* Frontend-inspired color scheme */
    Static {
        color: #f1f5f9;
    }

    Button.success {
        background: #4ade80;
        color: #000;
    }

    Button.error {
        background: #ef4444;
        color: #fff;
    }

    Button.warning {
        background: #eab308;
        color: #000;
    }

    Button.primary {
        background: #2563eb;
        color: #fff;
    }

    Button.default {
        background: #475569;
        color: #f1f5f9;
        border: solid #64748b;
    }

    DataTable {
        background: #1e293b;
        color: #f1f5f9;
    }

    DataTable > .datatable--header {
        background: #334155;
        color: #f1f5f9;
    }

    DataTable > .datatable--cursor {
        background: #475569;
    }

    Input {
        background: #334155;
        color: #f1f5f9;
        border: solid #64748b;
    }

    Label {
        color: #f1f5f9;
    }

    Footer {
        background: #334155;
        color: #f1f5f9;
    }

    #runtime-status {
        background: #1e293b;
        border: solid #64748b;
        color: #f1f5f9;
    }

    #system-info {
        background: #1e293b;
        border: solid #64748b;
        color: #f1f5f9;
    }

    #services-table, #images-table {
        background: #1e293b;
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


def run_tui():
    """Run the OpenRAG TUI application."""
    app = None
    try:
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
