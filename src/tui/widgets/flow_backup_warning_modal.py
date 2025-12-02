"""Flow backup warning modal for OpenRAG TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label


class FlowBackupWarningModal(ModalScreen[bool]):
    """Modal dialog to warn about flow backups before upgrade/reset."""

    DEFAULT_CSS = """
    FlowBackupWarningModal {
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

    def __init__(self, operation: str = "upgrade"):
        """Initialize the warning modal.
        
        Args:
            operation: The operation being performed ("upgrade" or "reset")
        """
        super().__init__()
        self.operation = operation

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label("⚠ Flow Backups Detected", id="title")
            yield Static(
                f"Flow backups found in ./flows/backup\n\n"
                f"Proceeding with {self.operation} will reset custom flows to defaults.\n"
                f"Your customizations are backed up and will need to be\n"
                f"manually imported and upgraded to work with the latest version.\n\n"
                f"Do you want to continue?",
                id="message"
            )
            with Horizontal(id="button-row"):
                yield Button("Cancel", id="cancel-btn")
                yield Button(f"Continue {self.operation.title()}", id="continue-btn")

    def on_mount(self) -> None:
        """Focus the cancel button by default for safety."""
        self.query_one("#cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "continue-btn":
            self.dismiss(True)  # User wants to continue
        else:
            self.dismiss(False)  # User cancelled
