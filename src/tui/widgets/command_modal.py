"""Command output modal dialog for OpenRAG TUI."""

import asyncio
from typing import Callable, List, Optional, AsyncIterator, Any

from textual.app import ComposeResult
from textual.worker import Worker
from textual.containers import Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label, RichLog
from rich.console import Console


class CommandOutputModal(ModalScreen):
    """Modal dialog for displaying command output in real-time."""

    DEFAULT_CSS = """
    CommandOutputModal {
        align: center middle;
    }

    #dialog {
        width: 90%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 0;
    }

    #title {
        background: $primary;
        color: $text;
        padding: 1 2;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #output-container {
        height: 1fr;
        padding: 0;
        margin: 0 1;
    }

    #command-output {
        height: 100%;
        border: solid $accent;
        padding: 1 2;
        margin: 1 0;
        background: $surface-darken-1;
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
    }
    """

    def __init__(
        self, 
        title: str, 
        command_generator: AsyncIterator[tuple[bool, str]],
        on_complete: Optional[Callable] = None
    ):
        """Initialize the modal dialog.
        
        Args:
            title: Title of the modal dialog
            command_generator: Async generator that yields (is_complete, message) tuples
            on_complete: Optional callback to run when command completes
        """
        super().__init__()
        self.title_text = title
        self.command_generator = command_generator
        self.on_complete = on_complete

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label(self.title_text, id="title")
            with ScrollableContainer(id="output-container"):
                yield RichLog(id="command-output", highlight=True, markup=True)
            with Container(id="button-row"):
                yield Button("Close", variant="primary", id="close-btn")

    def on_mount(self) -> None:
        """Start the command when the modal is mounted."""
        # Start the command but don't store the worker
        self.run_worker(self._run_command(), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close-btn":
            self.dismiss()

    async def _run_command(self) -> None:
        """Run the command and update the output in real-time."""
        output = self.query_one("#command-output", RichLog)
        
        try:
            async for is_complete, message in self.command_generator:
                # Simple approach: just append each line as it comes
                output.write(message + "\n")
                
                # Scroll to bottom
                container = self.query_one("#output-container", ScrollableContainer)
                container.scroll_end(animate=False)
                
                # If command is complete, update UI
                if is_complete:
                    output.write("[bold green]Command completed successfully[/bold green]\n")
                    # Call the completion callback if provided
                    if self.on_complete:
                        await asyncio.sleep(0.5)  # Small delay for better UX
                        self.on_complete()
        except Exception as e:
            output.write(f"[bold red]Error: {e}[/bold red]\n")
        
        # Enable the close button and focus it
        close_btn = self.query_one("#close-btn", Button)
        close_btn.disabled = False
        close_btn.focus()

# Made with Bob
