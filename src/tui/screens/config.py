"""Configuration screen for OpenRAG TUI."""

import os
import re
from zxcvbn import zxcvbn
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Static,
    Button,
    Input,
    Label,
    Checkbox,
)
from textual.validation import ValidationResult, Validator
from rich.text import Text
from pathlib import Path

from ..config_fields import CONFIG_SECTIONS, ConfigField
from ..managers.env_manager import EnvManager
from ..utils.validation import (
    validate_openai_api_key,
    validate_anthropic_api_key,
    validate_ollama_endpoint,
    validate_watsonx_endpoint,
    validate_documents_paths,
)


class OpenAIKeyValidator(Validator):
    """Validator for OpenAI API keys."""

    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.success()

        if validate_openai_api_key(value):
            return self.success()
        else:
            return self.failure("Invalid OpenAI API key format (should start with sk-)")


class AnthropicKeyValidator(Validator):
    """Validator for Anthropic API keys."""

    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.success()

        if validate_anthropic_api_key(value):
            return self.success()
        else:
            return self.failure("Invalid Anthropic API key format (should start with sk-ant-)")


class OllamaEndpointValidator(Validator):
    """Validator for Ollama endpoint URLs."""

    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.success()

        if validate_ollama_endpoint(value):
            return self.success()
        else:
            return self.failure("Invalid Ollama endpoint URL format")


class WatsonxEndpointValidator(Validator):
    """Validator for IBM watsonx.ai endpoint URLs."""

    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.success()

        if validate_watsonx_endpoint(value):
            return self.success()
        else:
            return self.failure("Invalid watsonx.ai endpoint URL format")


class DocumentsPathValidator(Validator):
    """Validator for documents paths."""

    def validate(self, value: str) -> ValidationResult:
        # Optional: allow empty value
        if not value:
            return self.success()

        is_valid, error_msg, _ = validate_documents_paths(value)
        if is_valid:
            return self.success()
        else:
            return self.failure(error_msg)


class PasswordValidator(Validator):
    """Validator for OpenSearch admin password using zxcvbn strength estimation."""

    # Minimum acceptable score (0-4 scale: 0=weak, 4=very strong)
    MIN_SCORE = 3

    def validate(self, value: str) -> ValidationResult:
        # Allow empty value (will be auto-generated)
        if not value:
            return self.success()

        # Use zxcvbn to evaluate password strength
        result = zxcvbn(value)
        score = result["score"]

        if score < self.MIN_SCORE:
            # Get feedback from zxcvbn
            feedback = result.get("feedback", {})
            warning = feedback.get("warning", "")
            suggestions = feedback.get("suggestions", [])

            # Build error message
            strength_labels = ["very weak", "weak", "fair", "strong", "very strong"]
            current_strength = strength_labels[score]

            if warning:
                return self.failure(f"Password is {current_strength}: {warning}")
            elif suggestions:
                return self.failure(f"Password is {current_strength}. {suggestions[0]}")
            else:
                return self.failure(f"Password is {current_strength}. Use a longer, more unique password.")

        return self.success()


class ConfigScreen(Screen):
    """Configuration screen for environment setup."""

    BINDINGS = [
        ("escape", "back", "Back"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+g", "generate", "Generate Passwords"),
    ]

    def __init__(self, mode: str = "full"):
        super().__init__()
        self.mode = mode  # "no_auth" or "full"
        self.env_manager = EnvManager()
        self.inputs = {}
        
        # Check if .env file exists
        self.has_env_file = self.env_manager.env_file.exists()

        # Load existing config if available
        self.env_manager.load_existing_env()

    def compose(self) -> ComposeResult:
        """Create the configuration screen layout."""
        # Removed top header bar and header text
        with Container(id="main-container"):
            with ScrollableContainer(id="config-scroll"):
                with Vertical(id="config-form"):
                    yield from self._create_all_fields()
            # Create button row - conditionally include Back button
            buttons = [
                Button("Generate Passwords", variant="default", id="generate-btn"),
                Button("Save Configuration", variant="success", id="save-btn"),
            ]
            # Only show Back button if .env file exists
            if self.has_env_file:
                buttons.append(Button("Back", variant="default", id="back-btn"))
            yield Horizontal(*buttons, classes="button-row")
        yield Footer()

    def _create_header_text(self) -> Text:
        """Create the configuration header text."""
        header_text = Text()

        if self.mode == "no_auth":
            header_text.append("Quick Setup - No Authentication\n", style="bold green")
            header_text.append(
                "Configure OpenRAG for local document processing only.\n\n", style="dim"
            )
        else:
            header_text.append("Full Setup - OAuth Integration\n", style="bold cyan")
            header_text.append(
                "Configure OpenRAG with cloud service integrations.\n\n", style="dim"
            )

        header_text.append("Required fields are marked with *\n", style="yellow")
        header_text.append("Use Ctrl+G to generate admin passwords\n", style="dim")

        return header_text

    # Map validator functions to Textual Validator classes
    VALIDATOR_MAP: dict = {
        validate_openai_api_key: OpenAIKeyValidator,
        validate_anthropic_api_key: AnthropicKeyValidator,
        validate_ollama_endpoint: OllamaEndpointValidator,
        validate_watsonx_endpoint: WatsonxEndpointValidator,
    }

    # Fields that need custom rendering beyond the standard pattern
    SPECIAL_FIELDS = {
        "opensearch_password",
        "opensearch_data_path",
        "langflow_superuser_password",
        "langflow_superuser",
        "google_oauth_client_id",
        "microsoft_graph_oauth_client_id",
        "openrag_documents_paths",
    }

    def _create_all_fields(self) -> ComposeResult:
        """Create all configuration fields from shared CONFIG_SECTIONS."""
        for section in CONFIG_SECTIONS:
            if section.advanced and self.mode != "full":
                continue

            yield Static(section.name, classes="tab-header")
            yield Static(" ")

            for field in section.fields:
                if field.advanced and self.mode != "full":
                    continue

                if field.name in self.SPECIAL_FIELDS:
                    renderer = getattr(self, f"_render_{field.name}")
                    yield from renderer(field)
                else:
                    yield from self._render_standard_field(field)

    def _render_standard_field(self, field: ConfigField) -> ComposeResult:
        """Render a standard field: label + helper + input + optional toggle."""
        label_text = field.label
        if field.required:
            label_text += " *"
        elif not field.secret:
            label_text += " (optional)"
        else:
            label_text += " (optional)"
        yield Label(label_text)

        if field.helper_text:
            yield Static(
                Text(field.helper_text, style="dim"),
                classes="helper-text",
            )

        current_value = getattr(self.env_manager.config, field.name, field.default) or ""
        validators = []
        if field.validator and field.validator in self.VALIDATOR_MAP:
            validators = [self.VALIDATOR_MAP[field.validator]()]

        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            password=field.secret,
            validators=validators,
            id=f"input-{field.name}",
        )

        if field.secret:
            with Horizontal(id=f"{field.name}-row"):
                yield input_widget
                yield Button("Show", id=f"toggle-{field.name}", variant="default")
        else:
            yield input_widget

        self.inputs[field.name] = input_widget
        yield Static(" ")

    # ── Special field renderers ──────────────────────────────────

    def _render_opensearch_password(self, field: ConfigField) -> ComposeResult:
        """OpenSearch password with strength validator and eye toggle."""
        yield Label("Admin Password *")
        yield Static(field.helper_text, classes="helper-text")
        current_value = getattr(self.env_manager.config, field.name, "")
        with Horizontal(id="opensearch-password-row"):
            input_widget = Input(
                placeholder=field.placeholder,
                value=current_value,
                password=True,
                id=f"input-{field.name}",
                validators=[PasswordValidator()],
            )
            yield input_widget
            self.inputs[field.name] = input_widget
            yield Button("👁", id=f"toggle-{field.name}", variant="default")
        yield Static(" ")

    def _render_opensearch_data_path(self, field: ConfigField) -> ComposeResult:
        """OpenSearch data path with file picker."""
        yield Label(field.label)
        yield Static(field.helper_text, classes="helper-text")
        current_value = getattr(self.env_manager.config, field.name, field.default)
        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            id=f"input-{field.name}",
        )
        yield input_widget
        yield Horizontal(
            Button("Pick…", id="pick-opensearch-data-btn"),
            id="opensearch-data-path-actions",
            classes="controls-row",
        )
        self.inputs[field.name] = input_widget
        yield Static(" ")

    def _render_langflow_superuser_password(self, field: ConfigField) -> ComposeResult:
        """Langflow password with generate checkbox and eye toggle."""
        with Horizontal():
            yield Label("Admin Password (optional)")
            yield Checkbox("Generate password", id="generate-langflow-password")
        current_value = getattr(self.env_manager.config, field.name, "")
        with Horizontal(id="langflow-password-row"):
            input_widget = Input(
                placeholder=field.placeholder,
                value=current_value,
                password=True,
                id=f"input-{field.name}",
            )
            yield input_widget
            self.inputs[field.name] = input_widget
            yield Button("👁", id=f"toggle-{field.name}", variant="default")
        yield Static(" ")

    def _render_langflow_superuser(self, field: ConfigField) -> ComposeResult:
        """Langflow username with conditional visibility."""
        yield Label("Admin Username *", id="langflow-username-label")
        current_value = getattr(self.env_manager.config, field.name, field.default)
        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            id=f"input-{field.name}",
        )
        yield input_widget
        self.inputs[field.name] = input_widget
        yield Static(" ", id="langflow-username-spacer")

    def _render_google_oauth_client_id(self, field: ConfigField) -> ComposeResult:
        """Google OAuth client ID with redirect URI helper."""
        yield Label(field.label)
        yield Static(
            Text(field.helper_text, style="dim"),
            classes="helper-text",
        )
        frontend_port = os.getenv("FRONTEND_PORT", "3000")
        yield Static(
            Text(
                f"Redirect URI: http://localhost:{frontend_port}/auth/callback (or your domain)",
                style="dim",
            ),
            classes="helper-text",
        )
        current_value = getattr(self.env_manager.config, field.name, "")
        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            id=f"input-{field.name}",
        )
        yield input_widget
        self.inputs[field.name] = input_widget
        yield Static(" ")

    def _render_microsoft_graph_oauth_client_id(self, field: ConfigField) -> ComposeResult:
        """Microsoft OAuth client ID with redirect URI helper."""
        yield Label(field.label)
        yield Static(
            Text(field.helper_text, style="dim"),
            classes="helper-text",
        )
        frontend_port = os.getenv("FRONTEND_PORT", "3000")
        yield Static(
            Text(
                f"Redirect URI: http://localhost:{frontend_port}/auth/callback (or your domain)",
                style="dim",
            ),
            classes="helper-text",
        )
        current_value = getattr(self.env_manager.config, field.name, "")
        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            id=f"input-{field.name}",
        )
        yield input_widget
        self.inputs[field.name] = input_widget
        yield Static(" ")

    def _render_openrag_documents_paths(self, field: ConfigField) -> ComposeResult:
        """Documents paths with validator and file picker."""
        yield Label(field.label)
        yield Static(field.helper_text, classes="helper-text")
        current_value = getattr(self.env_manager.config, field.name, "")
        input_widget = Input(
            placeholder=field.placeholder,
            value=current_value,
            validators=[DocumentsPathValidator()],
            validate_on=["submitted"],
            id=f"input-{field.name}",
        )
        yield input_widget
        yield Horizontal(
            Button("Pick…", id="pick-docs-btn"),
            id="docs-path-actions",
            classes="controls-row",
        )
        self.inputs[field.name] = input_widget
        yield Static(" ")


    def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        # Set initial visibility of username field based on password
        current_password = getattr(self.env_manager.config, "langflow_superuser_password", "")
        self._update_langflow_username_visibility(current_password)

        # Focus the first input field
        try:
            # Find the first input field and focus it
            inputs = self.query(Input)
            if inputs:
                inputs[0].focus()
        except Exception:
            pass

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes."""
        if event.checkbox.id == "generate-langflow-password":
            langflow_password_input = self.inputs.get("langflow_superuser_password")
            if event.value:
                # Generate password when checked
                password = self.env_manager.generate_secure_password()
                if langflow_password_input:
                    langflow_password_input.value = password
                    # Show username field
                    self._update_langflow_username_visibility(password)
                self.notify("Generated Langflow password", severity="information")
            else:
                # Clear password when unchecked (enable autologin)
                if langflow_password_input:
                    langflow_password_input.value = ""
                    # Hide username field
                    self._update_langflow_username_visibility("")
                self.notify("Cleared Langflow password - autologin enabled", severity="information")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "generate-btn":
            self.action_generate()
        elif event.button.id == "save-btn":
            self.action_save()
        elif event.button.id == "back-btn":
            self.action_back()
        elif event.button.id == "pick-docs-btn":
            self.action_pick_documents_path()
        elif event.button.id == "pick-opensearch-data-btn":
            self.action_pick_opensearch_data_path()
        elif event.button.id and event.button.id.startswith("toggle-"):
            # Generic toggle for password/secret field visibility
            field_name = event.button.id.removeprefix("toggle-")
            input_widget = self.inputs.get(field_name)
            if input_widget:
                input_widget.password = not input_widget.password
                # Eye emoji for main password fields, Show/Hide for others
                if field_name in ("opensearch_password", "langflow_superuser_password"):
                    event.button.label = "🙈" if not input_widget.password else "👁"
                else:
                    event.button.label = "Hide" if not input_widget.password else "Show"

    def action_generate(self) -> None:
        """Generate secure passwords for admin accounts."""
        # First sync input values to config to get current state
        opensearch_input = self.inputs.get("opensearch_password")
        if opensearch_input:
            self.env_manager.config.opensearch_password = opensearch_input.value

        # Only generate OpenSearch password if empty
        if not self.env_manager.config.opensearch_password:
            self.env_manager.config.opensearch_password = self.env_manager.generate_secure_password()

        # Update secret keys
        if not self.env_manager.config.langflow_secret_key:
            self.env_manager.config.langflow_secret_key = self.env_manager.generate_langflow_secret_key()

        # Update input fields with generated values
        if opensearch_input:
            opensearch_input.value = self.env_manager.config.opensearch_password

        self.notify("Generated secure password for OpenSearch", severity="information")

    def action_save(self) -> None:
        """Save the configuration."""
        # First, check Textual input validators
        validation_errors = []
        for field_name, input_widget in self.inputs.items():
            # Skip empty values as they may be optional or auto-generated
            if not input_widget.value:
                continue

            # Check if input has validators and manually validate
            if hasattr(input_widget, "validators") and input_widget.validators:
                for validator in input_widget.validators:
                    result = validator.validate(input_widget.value)
                    if result and not result.is_valid:
                        for failure in result.failures:
                            validation_errors.append(f"{field_name}: {failure.description}")

        if validation_errors:
            self.notify(
                "Validation failed:\n" + "\n".join(validation_errors[:3]),
                severity="error",
            )
            return

        # Update config from input fields
        for field_name, input_widget in self.inputs.items():
            setattr(self.env_manager.config, field_name, input_widget.value)

        # Generate secure defaults for empty passwords/keys BEFORE validation
        self.env_manager.setup_secure_defaults()

        # Validate the configuration
        if not self.env_manager.validate_config(self.mode):
            error_messages = []
            for field, error in self.env_manager.config.validation_errors.items():
                error_messages.append(f"{field}: {error}")

            self.notify(
                "Validation failed:\n" + "\n".join(error_messages[:3]),
                severity="error",
            )
            return

        # Save to file
        if self.env_manager.save_env_file():
            self.notify("Configuration saved successfully!", severity="information")
            # Go back to welcome screen
            self.dismiss()
        else:
            self.notify("Failed to save configuration", severity="error")

    def action_back(self) -> None:
        """Go back to welcome screen."""
        self.app.pop_screen()

    def action_pick_documents_path(self) -> None:
        """Open textual-fspicker to select a path and append it to the input."""
        try:
            import importlib

            fsp = importlib.import_module("textual_fspicker")
        except Exception:
            self.notify("textual-fspicker not available", severity="warning")
            return

        # Determine starting path from current input if possible
        input_widget = self.inputs.get("openrag_documents_paths")
        start = Path.home()
        if input_widget and input_widget.value:
            first = input_widget.value.split(",")[0].strip()
            if first:
                start = Path(first).expanduser()

        # Prefer SelectDirectory for directories; fallback to FileOpen
        PickerClass = getattr(fsp, "SelectDirectory", None) or getattr(
            fsp, "FileOpen", None
        )
        if PickerClass is None:
            self.notify(
                "No compatible picker found in textual-fspicker", severity="warning"
            )
            return
        try:
            picker = PickerClass(location=start)
        except Exception:
            try:
                picker = PickerClass(start)
            except Exception:
                self.notify("Could not initialize textual-fspicker", severity="warning")
                return

        def _append_path(result) -> None:
            if not result:
                return
            path_str = str(result)
            if input_widget is None:
                return
            current = input_widget.value or ""
            paths = [p.strip() for p in current.split(",") if p.strip()]
            if path_str not in paths:
                paths.append(path_str)
            input_widget.value = ",".join(paths)

        # Push with callback when supported; otherwise, use on_screen_dismissed fallback
        try:
            self.app.push_screen(picker, _append_path)  # type: ignore[arg-type]
        except TypeError:
            self._docs_pick_callback = _append_path  # type: ignore[attr-defined]
            self.app.push_screen(picker)

    def action_pick_opensearch_data_path(self) -> None:
        """Open textual-fspicker to select OpenSearch data directory."""
        try:
            import importlib

            fsp = importlib.import_module("textual_fspicker")
        except Exception:
            self.notify("textual-fspicker not available", severity="warning")
            return

        # Determine starting path from current input if possible
        input_widget = self.inputs.get("opensearch_data_path")
        start = Path.home()
        if input_widget and input_widget.value:
            path_str = input_widget.value.strip()
            if path_str:
                candidate = Path(path_str).expanduser()
                # If path doesn't exist, use parent or fallback to home
                if candidate.exists():
                    start = candidate
                elif candidate.parent.exists():
                    start = candidate.parent

        # Prefer SelectDirectory for directories; fallback to FileOpen
        PickerClass = getattr(fsp, "SelectDirectory", None) or getattr(
            fsp, "FileOpen", None
        )
        if PickerClass is None:
            self.notify(
                "No compatible picker found in textual-fspicker", severity="warning"
            )
            return
        try:
            picker = PickerClass(location=start)
        except Exception:
            try:
                picker = PickerClass(start)
            except Exception:
                self.notify("Could not initialize textual-fspicker", severity="warning")
                return

        def _set_path(result) -> None:
            if not result:
                return
            path_str = str(result)
            if input_widget is None:
                return
            input_widget.value = path_str

        # Push with callback when supported; otherwise, use on_screen_dismissed fallback
        try:
            self.app.push_screen(picker, _set_path)  # type: ignore[arg-type]
        except TypeError:
            self._opensearch_data_pick_callback = _set_path  # type: ignore[attr-defined]
            self.app.push_screen(picker)

    def on_screen_dismissed(self, event) -> None:  # type: ignore[override]
        try:
            # textual-fspicker screens should dismiss with a result; hand to callback if present
            cb = getattr(self, "_docs_pick_callback", None)
            if cb is not None:
                cb(getattr(event, "result", None))
                try:
                    delattr(self, "_docs_pick_callback")
                except Exception:
                    pass
            
            # Handle OpenSearch data path picker callback
            cb = getattr(self, "_opensearch_data_pick_callback", None)
            if cb is not None:
                cb(getattr(event, "result", None))
                try:
                    delattr(self, "_opensearch_data_pick_callback")
                except Exception:
                    pass
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for real-time validation feedback."""
        # Handle Langflow password changes - show/hide username field
        if event.input.id == "input-langflow_superuser_password":
            self._update_langflow_username_visibility(event.value)
        # This will trigger validation display in real-time
        pass

    def _update_langflow_username_visibility(self, password_value: str) -> None:
        """Show or hide the Langflow username field based on password presence."""
        has_password = bool(password_value and password_value.strip())

        # Get the widgets
        try:
            username_label = self.query_one("#langflow-username-label")
            username_input = self.query_one("#input-langflow_superuser")
            username_spacer = self.query_one("#langflow-username-spacer")

            # Show or hide based on password presence
            if has_password:
                username_label.display = True
                username_input.display = True
                username_spacer.display = True
            else:
                username_label.display = False
                username_input.display = False
                username_spacer.display = False
        except Exception:
            # Widgets don't exist yet, ignore
            pass
