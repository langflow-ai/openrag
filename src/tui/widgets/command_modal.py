"""Command output modal dialog for OpenRAG TUI."""

import asyncio
import inspect
from typing import Callable, Optional, AsyncIterator

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label, TextArea

from ..utils.clipboard import copy_text_to_clipboard


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
        margin: 1 0;
        background: $surface-darken-1;
    }

    #command-output > .text-area--content {
        padding: 1 2;
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

    #copy-status {
        text-align: center;
        margin-bottom: 1;
    }
    """

    def __init__(
        self,
        title: str,
        command_generator: AsyncIterator[tuple[bool, str]],
        on_complete: Optional[Callable] = None,
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
        self._output_text: str = ""
        self._status_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        with Container(id="dialog"):
            yield Label(self.title_text, id="title")
            with ScrollableContainer(id="output-container"):
                yield TextArea(
                    text="",
                    read_only=True,
                    show_line_numbers=False,
                    id="command-output",
                )
            with Container(id="button-row"):
                yield Button("Copy Output", variant="default", id="copy-btn")
                yield Button(
                    "Close", variant="primary", id="close-btn", disabled=True
                )
            yield Static("", id="copy-status")

    def on_mount(self) -> None:
        """Start the command when the modal is mounted."""
        # Start the command but don't store the worker
        self.run_worker(self._run_command(), exclusive=False)
        # Focus the output so users can select text immediately
        try:
            self.query_one("#command-output", TextArea).focus()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Cancel any pending timers when modal closes."""
        if self._status_task:
            self._status_task.cancel()
            self._status_task = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close-btn":
            self.dismiss()
        elif event.button.id == "copy-btn":
            self.copy_to_clipboard()

    async def _run_command(self) -> None:
        """Run the command and update the output in real-time."""
        output = self.query_one("#command-output", TextArea)
        container = self.query_one("#output-container", ScrollableContainer)

        try:
            async for is_complete, message in self.command_generator:
                self._append_output(message)
                output.text = self._output_text
                container.scroll_end(animate=False)

                # If command is complete, update UI
                if is_complete:
                    self._append_output("Command completed successfully")
                    output.text = self._output_text
                    container.scroll_end(animate=False)
                    # Call the completion callback if provided
                    if self.on_complete:
                        await asyncio.sleep(0.5)  # Small delay for better UX

                        def _invoke_callback() -> None:
                            callback_result = self.on_complete()
                            if inspect.isawaitable(callback_result):
                                asyncio.create_task(callback_result)

                        self.call_after_refresh(_invoke_callback)
        except Exception as e:
            self._append_output(f"Error: {e}")
            output.text = self._output_text
            container.scroll_end(animate=False)
        finally:
            # Enable the close button and focus it
            close_btn = self.query_one("#close-btn", Button)
            close_btn.disabled = False
            close_btn.focus()

    def _append_output(self, message: str) -> None:
        """Append a message to the output buffer."""
        if message is None:
            return
        message = message.rstrip("\n")
        if not message:
            return
        if self._output_text:
            self._output_text += "\n" + message
        else:
            self._output_text = message

    def copy_to_clipboard(self) -> None:
        """Copy the modal output to the clipboard."""
        if not self._output_text:
            message = "No output to copy yet"
            self.notify(message, severity="warning")
            status = self.query_one("#copy-status", Static)
            status.update(Text(message, style="bold yellow"))
            self._schedule_status_clear(status)
            return

        success, message = copy_text_to_clipboard(self._output_text)
        self.notify(message, severity="information" if success else "error")
        status = self.query_one("#copy-status", Static)
        style = "bold green" if success else "bold red"
        status.update(Text(message, style=style))
        self._schedule_status_clear(status)

    def _schedule_status_clear(self, widget: Static, delay: float = 3.0) -> None:
        """Clear the status message after a delay."""
        if self._status_task:
            self._status_task.cancel()

        async def _clear() -> None:
            try:
                await asyncio.sleep(delay)
                widget.update("")
            except asyncio.CancelledError:
                pass

        self._status_task = asyncio.create_task(_clear())


# Made with Bob
