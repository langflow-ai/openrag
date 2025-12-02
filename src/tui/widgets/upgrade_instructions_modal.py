"""Upgrade instructions modal for OpenRAG TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label


class UpgradeInstructionsModal(ModalScreen[bool]):
    """Modal dialog showing upgrade instructions when not on latest version."""

    DEFAULT_CSS = """
    UpgradeInstructionsModal {
        align: center middle;
    }

    #dialog {
        width: 75;
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

    def __init__(self, current_version: str, latest_version: str):
        """Initialize the upgrade instructions modal.
        
        Args:
            current_version: Current TUI version
            latest_version: Latest available version
        """
        super().__init__()
        self.current_version = current_version
        self.latest_version = latest_version

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label("📦 Upgrade Available", id="title")
            yield Static(
                f"Current version: {self.current_version}\n"
                f"Latest version: {self.latest_version}\n\n"
                "To upgrade the TUI:\n"
                "1. Exit TUI (press 'q')\n"
                "2. Run one of:\n"
                "   • pip install --upgrade openrag\n"
                "   • uv pip install --upgrade openrag\n"
                "   • uvx --from openrag openrag\n"
                "3. Restart: openrag\n\n"
                "After upgrading, containers will automatically use the new version.",
                id="message"
            )
            with Horizontal(id="button-row"):
                yield Button("Close", id="close-btn")

    def on_mount(self) -> None:
        """Focus the close button."""
        self.query_one("#close-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        self.dismiss(True)  # Just close the modal

