"""Flow backup warning modal for OpenRAG TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label, Checkbox


class FlowBackupWarningModal(ModalScreen[tuple[bool, bool]]):
    """Modal dialog to warn about flow backups before upgrade/reset.
    
    Returns tuple of (continue, delete_backups)
    """

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

    #checkbox-container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 0 2;
    }

    #delete-backups-checkbox {
        width: auto;
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
                f"Flow backups found in your flows/backup directory.\n\n"
                f"Proceeding with {self.operation} will reset custom flows to defaults.\n"
                f"Your customizations are backed up in the flows/backup/ directory.\n\n"
                f"Choose whether to keep or delete the backup files:",
                id="message"
            )
            with Vertical(id="checkbox-container"):
                yield Checkbox("Delete backup files", id="delete-backups-checkbox", value=False)
            with Horizontal(id="button-row"):
                yield Button("Cancel", id="cancel-btn")
                yield Button(f"Continue {self.operation.title()}", id="continue-btn")

    def on_mount(self) -> None:
        """Focus the cancel button by default for safety."""
        self.query_one("#cancel-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "continue-btn":
            delete_backups = self.query_one("#delete-backups-checkbox", Checkbox).value
            self.dismiss((True, delete_backups))  # User wants to continue, with delete preference
        else:
            self.dismiss((False, False))  # User cancelled
