"""Prune options modal for OpenRAG TUI."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label


class PruneOptionsModal(ModalScreen[str]):
    """Modal dialog to choose prune options."""

    DEFAULT_CSS = """
    PruneOptionsModal {
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
        background: #ec4899;
        color: #fafafa;
        padding: 1 2;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #message {
        padding: 2;
        color: #fafafa;
        text-align: left;
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
        min-width: 20;
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

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label("🗑️  Prune Images", id="title")
            yield Static(
                "Choose how to prune OpenRAG images:\n\n"
                "• Prune Unused Only\n"
                "  Remove old versions, keep latest and currently used images\n"
                "  (Services will continue running)\n\n"
                "• Stop & Prune All\n"
                "  Stop all services and remove ALL OpenRAG images\n"
                "  (Frees maximum disk space, images will be re-downloaded on next start)\n\n"
                "What would you like to do?",
                id="message",
            )
            with Horizontal(id="button-row"):
                yield Button("Cancel", id="cancel-btn")
                yield Button("Prune Unused Only", id="prune-unused-btn", variant="primary")
                yield Button("Stop & Prune All", id="prune-all-btn", variant="warning")

    def on_mount(self) -> None:
        """Focus the prune unused button by default."""
        self.query_one("#prune-unused-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "prune-unused-btn":
            self.dismiss("unused")  # Prune only unused images
        elif event.button.id == "prune-all-btn":
            self.dismiss("all")  # Stop services and prune all
        else:
            self.dismiss("cancel")  # User cancelled
