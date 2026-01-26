"""Version mismatch warning modal for OpenRAG TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label


class VersionMismatchWarningModal(ModalScreen[bool]):
    """Modal dialog to warn about version mismatch before starting services."""

    DEFAULT_CSS = """
    VersionMismatchWarningModal {
        align: center middle;
    }

    #dialog {
        width: 70;
        height: auto;
        border: solid #3f3f46;
        background: #27272a;
        padding: 0;
    }

    #title {
        background: #3f3f46;
        color: #fafafa;
        padding: 1 2;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #message {
        padding: 2;
        color: #fafafa;
        text-align: center;
    }

    #button-row {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1;
        margin-top: 1;
    }

    #button-row Button {
        margin: 0 1;
        min-width: 16;
        background: #27272a;
        color: #fafafa;
        border: round #52525b;
        text-style: none;
        tint: transparent 0%;
    }

    #button-row Button:hover {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #52525b;
        tint: transparent 0%;
        text-style: none;
    }

    #button-row Button:focus {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #ec4899;
        tint: transparent 0%;
        text-style: none;
    }
    """

    def __init__(self, container_version: str, tui_version: str):
        """Initialize the warning modal.
        
        Args:
            container_version: Version of existing containers
            tui_version: Current TUI version
        """
        super().__init__()
        self.container_version = container_version
        self.tui_version = tui_version

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label("⚠ Version Mismatch Detected", id="title")
            yield Static(
                f"Existing containers are running version {self.container_version}\n"
                f"Current TUI version is {self.tui_version}\n\n"
                f"Starting services will update containers to version {self.tui_version}.\n"
                f"This may cause compatibility issues with your flows.\n\n"
                f"⚠️  Please backup your flows before continuing.\n"
                f"   Customizations to OpenRAG built-in flows are backed up in ~/.openrag/flows/backup/\n"
                f"   Other user created flows are not backed up automatically.\n\n"
                f"Do you want to continue?",
                id="message"
            )
            with Horizontal(id="button-row"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Continue", id="continue-btn")

    def on_mount(self) -> None:
        """Focus the cancel button by default for safety."""
        self.query_one("#cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "continue-btn":
            self.dismiss(True)  # User wants to continue
        else:
            self.dismiss(False)  # User cancelled

