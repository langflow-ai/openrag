"""Command output modal dialog for OpenRAG TUI."""

import asyncio
import inspect
from typing import Callable, Optional, AsyncIterator

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, Label, TextArea, Footer

from ..utils.clipboard import copy_text_to_clipboard
from .waves import Waves


class CommandOutputModal(ModalScreen):
    """Modal dialog for displaying command output in real-time."""

    BINDINGS = [
        ("w,+", "add_wave", "Add"),
        ("r,-", "remove_wave", "Remove"),
        ("p", "pause_waves", "Pause"),
        ("f", "speed_up", "Faster"),
        ("s", "speed_down", "Slower"),
    ]

    DEFAULT_CSS = """
    CommandOutputModal {
        align: center middle;
        overflow: hidden;
    }

    #waves-background {
        width: 100%;
        height: 100%;
        layer: background;
        overflow: hidden;
    }

    #dialog {
        width: 90%;
        height: 90%;
        border: solid #3f3f46;
        background: #27272a;
        padding: 0;
        overflow: hidden;
    }

    #title {
        background: #3f3f46;
        color: #fafafa;
        padding: 1 2;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #command-output {
        height: 1fr;
        border: solid #3f3f46;
        margin: 1;
        background: #18181b;
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

    #button-row Button > Static {
        background: transparent !important;
        color: #fafafa !important;
        text-style: none;
    }

    #button-row Button > * {
        background: transparent !important;
        color: #fafafa !important;
    }

    #button-row Button:hover {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #52525b;
        tint: transparent 0%;
        text-style: none;
    }

    #button-row Button:hover > Static {
        background: transparent !important;
        color: #fafafa !important;
        text-style: none;
    }

    #button-row Button:hover > * {
        background: transparent !important;
        color: #fafafa !important;
    }

    #button-row Button:focus {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #ec4899;
        tint: transparent 0%;
        text-style: none;
    }

    #button-row Button:focus > Static {
        background: transparent !important;
        color: #fafafa !important;
        text-style: none;
    }

    #button-row Button:focus > * {
        background: transparent !important;
        color: #fafafa !important;
    }

    #button-row Button.-active {
        background: #27272a !important;
        color: #fafafa !important;
        border: round #ec4899;
        tint: transparent 0%;
        text-style: none;
    }

    #button-row Button.-active > Static {
        background: transparent !important;
        color: #fafafa !important;
        text-style: none;
    }

    #button-row Button.-active > * {
        background: transparent !important;
        color: #fafafa !important;
    }

    #button-row Button:disabled {
        background: #27272a;
        color: #52525b;
        border: round #3f3f46;
    }

    #button-row Button:disabled > Static {
        background: transparent;
        color: #52525b;
    }

    #copy-status {
        text-align: center;
        margin-bottom: 1;
        color: #a1a1aa;
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
            command_generator: Async generator that yields (is_complete, message) or (is_complete, message, replace_last) tuples
            on_complete: Optional callback to run when command completes
        """
        super().__init__()
        self.title_text = title
        self.command_generator = command_generator
        self.on_complete = on_complete
        self._output_lines: list[str] = []
        self._layer_line_map: dict[str, int] = {}  # Maps layer ID to line index
        self._status_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        """Create the modal dialog layout."""
        yield Waves(id="waves-background")
        with Container(id="dialog"):
            yield Label(self.title_text, id="title")
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
        yield Footer()

    def on_mount(self) -> None:
        """Start the command when the modal is mounted."""
        # Start the command but don't store the worker
        self.run_worker(self._run_command(), exclusive=False)

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

    def action_add_wave(self) -> None:
        """Add a wave to the animation."""
        waves = self.query_one("#waves-background", Waves)
        waves._add_wavelet()

    def action_remove_wave(self) -> None:
        """Remove a wave from the animation."""
        waves = self.query_one("#waves-background", Waves)
        if waves.wavelets:
            waves.wavelets.pop()

    def action_pause_waves(self) -> None:
        """Pause/unpause the wave animation."""
        waves = self.query_one("#waves-background", Waves)
        waves.paused = not waves.paused

    def action_speed_up(self) -> None:
        """Increase wave speed."""
        waves = self.query_one("#waves-background", Waves)
        for w in waves.wavelets:
            w.speed = min(2.0, w.speed * 1.2)

    def action_speed_down(self) -> None:
        """Decrease wave speed."""
        waves = self.query_one("#waves-background", Waves)
        for w in waves.wavelets:
            w.speed = max(0.1, w.speed * 0.8)

    async def _run_command(self) -> None:
        """Run the command and update the output in real-time."""
        output = self.query_one("#command-output", TextArea)

        try:
            async for result in self.command_generator:
                # Handle both (is_complete, message) and (is_complete, message, replace_last) tuples
                if len(result) == 2:
                    is_complete, message = result
                    replace_last = False
                else:
                    is_complete, message, replace_last = result

                self._update_output(message, replace_last)
                output.text = "\n".join(self._output_lines)

                # Move cursor to end to trigger scroll
                output.move_cursor((len(self._output_lines), 0))

                # If command is complete, update UI
                if is_complete:
                    self._update_output("Command completed successfully", False)
                    output.text = "\n".join(self._output_lines)
                    output.move_cursor((len(self._output_lines), 0))

                    # Call the completion callback if provided
                    if self.on_complete:
                        await asyncio.sleep(0.5)  # Small delay for better UX

                        def _invoke_callback() -> None:
                            callback_result = self.on_complete()
                            if inspect.isawaitable(callback_result):
                                asyncio.create_task(callback_result)

                        self.call_after_refresh(_invoke_callback)
        except Exception as e:
            self._update_output(f"Error: {e}", False)
            output.text = "\n".join(self._output_lines)
            output.move_cursor((len(self._output_lines), 0))
        finally:
            # Enable the close button and focus it
            close_btn = self.query_one("#close-btn", Button)
            close_btn.disabled = False
            close_btn.focus()

    def _update_output(self, message: str, replace_last: bool = False) -> None:
        """Update the output buffer by appending or replacing the last line.

        Args:
            message: The message to add or use as replacement
            replace_last: If True, replace the last line (or layer-specific line); if False, append new line
        """
        if message is None:
            return
        message = message.rstrip("\n")
        if not message:
            return

        # Always check if this is a layer update (regardless of replace_last flag)
        parts = message.split(None, 1)
        if parts:
            potential_layer_id = parts[0]

            # Check if this looks like a layer ID (hex string, 12 chars for Docker layers)
            if len(potential_layer_id) == 12 and all(c in '0123456789abcdefABCDEF' for c in potential_layer_id):
                # This is a layer message
                if potential_layer_id in self._layer_line_map:
                    # Update the existing line for this layer
                    line_idx = self._layer_line_map[potential_layer_id]
                    if 0 <= line_idx < len(self._output_lines):
                        self._output_lines[line_idx] = message
                        return
                else:
                    # New layer, add it and track the line index
                    self._layer_line_map[potential_layer_id] = len(self._output_lines)
                    self._output_lines.append(message)
                    return

        # Not a layer message, handle normally
        if replace_last:
            # Fallback: just replace the last line
            if self._output_lines:
                self._output_lines[-1] = message
            else:
                self._output_lines.append(message)
        else:
            # Append as a new line
            self._output_lines.append(message)

    def copy_to_clipboard(self) -> None:
        """Copy the modal output to the clipboard."""
        if not self._output_lines:
            message = "No output to copy yet"
            self.notify(message, severity="warning")
            status = self.query_one("#copy-status", Static)
            status.update(Text(message, style="bold yellow"))
            self._schedule_status_clear(status)
            return

        output_text = "\n".join(self._output_lines)
        success, message = copy_text_to_clipboard(output_text)
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
