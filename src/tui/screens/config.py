"""Configuration screen for OpenRAG TUI."""

import re
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Header,
    Footer,
    Static,
    Button,
    Input,
    Label,
    TabbedContent,
    TabPane,
    Checkbox,
)
from textual.validation import ValidationResult, Validator
from rich.text import Text
from pathlib import Path

from ..managers.env_manager import EnvManager
from ..utils.validation import validate_openai_api_key, validate_documents_paths
from pathlib import Path


class OpenAIKeyValidator(Validator):
    """Validator for OpenAI API keys."""

    def validate(self, value: str) -> ValidationResult:
        if not value:
            return self.success()

        if validate_openai_api_key(value):
            return self.success()
        else:
            return self.failure("Invalid OpenAI API key format (should start with sk-)")


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
    """Validator for OpenSearch admin password."""

    def validate(self, value: str) -> ValidationResult:
        # Allow empty value (will be auto-generated)
        if not value:
            return self.success()

        # Minimum length: 8 characters
        if len(value) < 8:
            return self.failure("Password must be at least 8 characters long")

        # Check for required character types
        has_uppercase = bool(re.search(r"[A-Z]", value))
        has_lowercase = bool(re.search(r"[a-z]", value))
        has_digit = bool(re.search(r"[0-9]", value))
        has_special = bool(re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", value))

        missing = []
        if not has_uppercase:
            missing.append("uppercase letter")
        if not has_lowercase:
            missing.append("lowercase letter")
        if not has_digit:
            missing.append("digit")
        if not has_special:
            missing.append("special character")

        if missing:
            return self.failure(f"Password must contain: {', '.join(missing)}")

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

        # Load existing config if available
        self.env_manager.load_existing_env()

    def compose(self) -> ComposeResult:
        """Create the configuration screen layout."""
        # Removed top header bar and header text
        with Container(id="main-container"):
            with ScrollableContainer(id="config-scroll"):
                with Vertical(id="config-form"):
                    yield from self._create_all_fields()
            yield Horizontal(
                Button("Generate Passwords", variant="default", id="generate-btn"),
                Button("Save Configuration", variant="success", id="save-btn"),
                Button("Back", variant="default", id="back-btn"),
                classes="button-row",
            )
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

    def _create_all_fields(self) -> ComposeResult:
        """Create all configuration fields in a single scrollable layout."""

        # Admin Credentials Section
        yield Static("Admin Credentials", classes="tab-header")
        yield Static(" ")

        # OpenSearch Admin Password
        yield Label("OpenSearch Admin Password *")
        yield Static(
            "Min 8 chars with uppercase, lowercase, digit, and special character",
            classes="helper-text",
        )
        current_value = getattr(self.env_manager.config, "opensearch_password", "")
        with Horizontal(id="opensearch-password-row"):
            input_widget = Input(
                placeholder="Auto-generated secure password",
                value=current_value,
                password=True,
                id="input-opensearch_password",
                validators=[PasswordValidator()],
            )
            yield input_widget
            self.inputs["opensearch_password"] = input_widget
            yield Button("👁", id="toggle-opensearch-password", variant="default")
        yield Static(" ")

        # Langflow Admin Password
        with Horizontal():
            yield Label("Langflow Admin Password (optional)")
            yield Checkbox("Generate password", id="generate-langflow-password")
        current_value = getattr(
            self.env_manager.config, "langflow_superuser_password", ""
        )
        with Horizontal(id="langflow-password-row"):
            input_widget = Input(
                placeholder="Langflow password",
                value=current_value,
                password=True,
                id="input-langflow_superuser_password",
            )
            yield input_widget
            self.inputs["langflow_superuser_password"] = input_widget
            yield Button("👁", id="toggle-langflow-password", variant="default")
        yield Static(" ")

        # Langflow Admin Username - conditionally displayed based on password
        current_password = getattr(self.env_manager.config, "langflow_superuser_password", "")
        yield Label("Langflow Admin Username *", id="langflow-username-label")
        current_value = getattr(self.env_manager.config, "langflow_superuser", "")
        input_widget = Input(
            placeholder="admin", value=current_value, id="input-langflow_superuser"
        )
        yield input_widget
        self.inputs["langflow_superuser"] = input_widget
        yield Static(" ", id="langflow-username-spacer")

        yield Static(" ")

        # API Keys Section
        yield Static("API Keys", classes="tab-header")
        yield Static(" ")

        # OpenAI API Key
        yield Label("OpenAI API Key")
        # Where to create OpenAI keys (helper above the box)
        yield Static(
            Text("Get a key: https://platform.openai.com/api-keys", style="dim"),
            classes="helper-text",
        )
        yield Static(
            Text("Can also be provided during onboarding", style="dim italic"),
            classes="helper-text",
        )
        current_value = getattr(self.env_manager.config, "openai_api_key", "")
        with Horizontal(id="openai-key-row"):
            input_widget = Input(
                placeholder="sk-...",
                value=current_value,
                password=True,
                validators=[OpenAIKeyValidator()],
                id="input-openai_api_key",
            )
            yield input_widget
            self.inputs["openai_api_key"] = input_widget
            yield Button("Show", id="toggle-openai-key", variant="default")
        yield Static(" ")

        # Add OAuth fields only in full mode
        if self.mode == "full":
            # Google OAuth Client ID
            yield Label("Google OAuth Client ID")
            # Where to create Google OAuth credentials (helper above the box)
            yield Static(
                Text(
                    "Create credentials: https://console.cloud.google.com/apis/credentials",
                    style="dim",
                ),
                classes="helper-text",
            )
            # Callback URL guidance for Google OAuth
            yield Static(
                Text(
                    "Important: add an Authorized redirect URI to your Google OAuth app(s):\n"
                    "  - Local: http://localhost:3000/auth/callback\n"
                    "  - Prod:  https://your-domain.com/auth/callback\n"
                    "If you use separate apps for login and connectors, add this URL to BOTH.",
                    style="dim",
                ),
                classes="helper-text",
            )
            current_value = getattr(
                self.env_manager.config, "google_oauth_client_id", ""
            )
            input_widget = Input(
                placeholder="xxx.apps.googleusercontent.com",
                value=current_value,
                id="input-google_oauth_client_id",
            )
            yield input_widget
            self.inputs["google_oauth_client_id"] = input_widget
            yield Static(" ")

            # Google OAuth Client Secret
            yield Label("Google OAuth Client Secret")
            current_value = getattr(
                self.env_manager.config, "google_oauth_client_secret", ""
            )
            with Horizontal(id="google-secret-row"):
                input_widget = Input(
                    placeholder="",
                    value=current_value,
                    password=True,
                    id="input-google_oauth_client_secret",
                )
                yield input_widget
                self.inputs["google_oauth_client_secret"] = input_widget
                yield Button("Show", id="toggle-google-secret", variant="default")
            yield Static(" ")

            # Microsoft Graph Client ID
            yield Label("Microsoft Graph Client ID")
            # Where to create Microsoft app registrations (helper above the box)
            yield Static(
                Text(
                    "Create app: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
                    style="dim",
                ),
                classes="helper-text",
            )
            # Callback URL guidance for Microsoft OAuth
            yield Static(
                Text(
                    "Important: configure a Web redirect URI for your Microsoft app(s):\n"
                    "  - Local: http://localhost:3000/auth/callback\n"
                    "  - Prod:  https://your-domain.com/auth/callback\n"
                    "If you use separate apps for login and connectors, add this URI to BOTH.",
                    style="dim",
                ),
                classes="helper-text",
            )
            current_value = getattr(
                self.env_manager.config, "microsoft_graph_oauth_client_id", ""
            )
            input_widget = Input(
                placeholder="",
                value=current_value,
                id="input-microsoft_graph_oauth_client_id",
            )
            yield input_widget
            self.inputs["microsoft_graph_oauth_client_id"] = input_widget
            yield Static(" ")

            # Microsoft Graph Client Secret
            yield Label("Microsoft Graph Client Secret")
            current_value = getattr(
                self.env_manager.config, "microsoft_graph_oauth_client_secret", ""
            )
            with Horizontal(id="microsoft-secret-row"):
                input_widget = Input(
                    placeholder="",
                    value=current_value,
                    password=True,
                    id="input-microsoft_graph_oauth_client_secret",
                )
                yield input_widget
                self.inputs["microsoft_graph_oauth_client_secret"] = input_widget
                yield Button("Show", id="toggle-microsoft-secret", variant="default")
            yield Static(" ")

            # AWS Access Key ID
            yield Label("AWS Access Key ID")
            # Where to create AWS keys (helper above the box)
            yield Static(
                Text(
                    "Create keys: https://console.aws.amazon.com/iam/home#/security_credentials",
                    style="dim",
                ),
                classes="helper-text",
            )
            current_value = getattr(self.env_manager.config, "aws_access_key_id", "")
            input_widget = Input(
                placeholder="", value=current_value, id="input-aws_access_key_id"
            )
            yield input_widget
            self.inputs["aws_access_key_id"] = input_widget
            yield Static(" ")

            # AWS Secret Access Key
            yield Label("AWS Secret Access Key")
            current_value = getattr(
                self.env_manager.config, "aws_secret_access_key", ""
            )
            input_widget = Input(
                placeholder="",
                value=current_value,
                password=True,
                id="input-aws_secret_access_key",
            )
            yield input_widget
            self.inputs["aws_secret_access_key"] = input_widget
            yield Static(" ")

        yield Static(" ")

        # Other Settings Section
        yield Static("Others", classes="tab-header")
        yield Static(" ")

        # Documents Paths (optional) + picker action button on next line
        yield Label("Documents Paths")
        current_value = getattr(self.env_manager.config, "openrag_documents_paths", "")
        input_widget = Input(
            placeholder="./documents,/path/to/more/docs",
            value=current_value,
            validators=[DocumentsPathValidator()],
            id="input-openrag_documents_paths",
        )
        yield input_widget
        # Actions row with pick button
        yield Horizontal(
            Button("Pick…", id="pick-docs-btn"),
            id="docs-path-actions",
            classes="controls-row",
        )
        self.inputs["openrag_documents_paths"] = input_widget
        yield Static(" ")

        # Langflow Auth Settings - These are automatically configured based on password presence
        # Not shown in UI; set in env_manager.setup_secure_defaults()

        # Add optional fields only in full mode
        if self.mode == "full":
            # Webhook Base URL
            yield Label("Webhook Base URL")
            current_value = getattr(self.env_manager.config, "webhook_base_url", "")
            input_widget = Input(
                placeholder="https://your-domain.com",
                value=current_value,
                id="input-webhook_base_url",
            )
            yield input_widget
            self.inputs["webhook_base_url"] = input_widget
            yield Static(" ")

            # Langflow Public URL
            yield Label("Langflow Public URL")
            current_value = getattr(self.env_manager.config, "langflow_public_url", "")
            input_widget = Input(
                placeholder="http://localhost:7860",
                value=current_value,
                id="input-langflow_public_url",
            )
            yield input_widget
            self.inputs["langflow_public_url"] = input_widget
            yield Static(" ")

    def _create_field(
        self,
        field_name: str,
        display_name: str,
        placeholder: str,
        can_generate: bool,
        required: bool = False,
    ) -> ComposeResult:
        """Create a single form field."""
        # Create label
        label_text = f"{display_name}"
        if required:
            label_text += " *"

        yield Label(label_text)

        # Get current value
        current_value = getattr(self.env_manager.config, field_name, "")

        # Create input with appropriate validator
        if field_name == "openai_api_key":
            input_widget = Input(
                placeholder=placeholder,
                value=current_value,
                password=True,
                validators=[OpenAIKeyValidator()],
                id=f"input-{field_name}",
            )
        elif field_name == "openrag_documents_paths":
            input_widget = Input(
                placeholder=placeholder,
                value=current_value,
                validators=[DocumentsPathValidator()],
                id=f"input-{field_name}",
            )
        elif "password" in field_name or "secret" in field_name:
            input_widget = Input(
                placeholder=placeholder,
                value=current_value,
                password=True,
                id=f"input-{field_name}",
            )
        else:
            input_widget = Input(
                placeholder=placeholder, value=current_value, id=f"input-{field_name}"
            )

        yield input_widget
        self.inputs[field_name] = input_widget

        # Add spacing
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
        elif event.button.id == "toggle-opensearch-password":
            # Toggle OpenSearch password visibility
            input_widget = self.inputs.get("opensearch_password")
            if input_widget:
                input_widget.password = not input_widget.password
                event.button.label = "🙈" if not input_widget.password else "👁"
        elif event.button.id == "toggle-langflow-password":
            # Toggle Langflow password visibility
            input_widget = self.inputs.get("langflow_superuser_password")
            if input_widget:
                input_widget.password = not input_widget.password
                event.button.label = "🙈" if not input_widget.password else "👁"

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
            if hasattr(input_widget, "validate") and input_widget.value:
                result = input_widget.validate(input_widget.value)
                if result and not result.is_valid:
                    for failure in result.failures:
                        validation_errors.append(f"{field_name}: {failure.description}")

        if validation_errors:
            self.notify(
                f"Validation failed:\n" + "\n".join(validation_errors[:3]),
                severity="error",
            )
            return

        # Update config from input fields
        for field_name, input_widget in self.inputs.items():
            setattr(self.env_manager.config, field_name, input_widget.value)

        # Validate the configuration
        if not self.env_manager.validate_config(self.mode):
            error_messages = []
            for field, error in self.env_manager.config.validation_errors.items():
                error_messages.append(f"{field}: {error}")

            self.notify(
                f"Validation failed:\n" + "\n".join(error_messages[:3]),
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
