"""Environment configuration manager for OpenRAG TUI."""

import os
import secrets
import string
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from utils.logging_config import get_logger

from ..utils.validation import (
    validate_documents_paths,
    validate_google_oauth_client_id,
    validate_non_empty,
    validate_openai_api_key,
    validate_url,
)

logger = get_logger(__name__)


@dataclass
class EnvConfig:
    """Environment configuration data."""

    # Core settings
    openai_api_key: str = ""
    opensearch_password: str = ""
    opensearch_username: str = "admin"
    opensearch_host: str = "opensearch"
    opensearch_port: str = "9200"
    opensearch_index_name: str = "documents"
    langflow_secret_key: str = ""
    langflow_superuser: str = "admin"
    langflow_superuser_password: str = ""
    langflow_chat_flow_id: str = "1098eea1-6649-4e1d-aed1-b77249fb8dd0"
    langflow_ingest_flow_id: str = "5488df7c-b93f-4f87-a446-b67028bc0813"
    langflow_url_ingest_flow_id: str = "72c3d17c-2dac-4a73-b48a-6518473d7830"

    # Provider API keys and endpoints
    anthropic_api_key: str = ""
    ollama_endpoint: str = ""
    watsonx_api_key: str = ""
    watsonx_endpoint: str = ""
    watsonx_project_id: str = ""

    # OAuth settings
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    microsoft_graph_oauth_client_id: str = ""
    microsoft_graph_oauth_client_secret: str = ""

    # Optional settings
    webhook_base_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    langflow_public_url: str = ""

    # Langfuse settings (optional)
    langfuse_secret_key: str = ""
    langfuse_public_key: str = ""
    langfuse_host: str = ""

    # Langflow auth settings
    langflow_auto_login: str = "False"
    langflow_new_user_is_active: str = "False"
    langflow_enable_superuser_cli: str = "False"
    
    # Ingestion settings
    disable_ingest_with_langflow: str = "False"
    nudges_flow_id: str = "ebc01d31-1976-46ce-a385-b0240327226c"
    ingest_sample_data: str = "True"

    # Document paths (comma-separated) - use centralized location by default
    openrag_documents_paths: str = "$HOME/.openrag/documents"

    # Volume mount paths - use centralized location by default
    openrag_documents_path: str = "$HOME/.openrag/documents"  # Primary documents path for compose
    openrag_keys_path: str = "$HOME/.openrag/keys"
    openrag_flows_path: str = "$HOME/.openrag/flows"
    openrag_config_path: str = "$HOME/.openrag/config"
    openrag_data_path: str = "$HOME/.openrag/data"  # Backend data (conversations, tokens, etc.)
    opensearch_data_path: str = "$HOME/.openrag/data/opensearch-data"
    openrag_tui_config_path_legacy: str = "$HOME/.openrag/tui/config"
    
    # Container version (linked to TUI version)
    openrag_version: str = ""

    # Validation errors
    validation_errors: Dict[str, str] = field(default_factory=dict)


class EnvManager:
    """Manages environment configuration for OpenRAG."""

    def __init__(self, env_file: Optional[Path] = None):
        if env_file:
            self.env_file = env_file
        else:
            # Use centralized location for TUI .env file
            from utils.paths import get_tui_env_file, get_legacy_paths
            self.env_file = get_tui_env_file()
            
            # Check for legacy .env in current directory and migrate if needed
            legacy_env = get_legacy_paths()["tui_env"]
            if not self.env_file.exists() and legacy_env.exists():
                try:
                    import shutil
                    self.env_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy_env, self.env_file)
                    logger.info(f"Migrated .env from {legacy_env} to {self.env_file}")


                except Exception as e:
                    logger.warning(f"Failed to migrate .env file: {e}")
        
        self.config = EnvConfig()

    def generate_secure_password(self) -> str:
        """Generate a secure password for OpenSearch."""
        # Ensure at least one character from each category
        symbols = "!@#$%^&*"

        # Guarantee at least one of each type
        password_chars = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
            secrets.choice(symbols),
        ]

        # Fill remaining 12 characters with random choices from all categories
        alphabet = string.ascii_letters + string.digits + symbols
        password_chars.extend(secrets.choice(alphabet) for _ in range(12))

        # Shuffle to avoid predictable patterns
        secrets.SystemRandom().shuffle(password_chars)

        return "".join(password_chars)

    def generate_langflow_secret_key(self) -> str:
        """Generate a secure secret key for Langflow."""
        return secrets.token_urlsafe(32)

    def _quote_env_value(self, value: str) -> str:
        """Single quote all environment variable values for consistency."""
        if not value:
            return "''"

        # Escape any existing single quotes by replacing ' with '\''
        escaped_value = value.replace("'", "'\\''")
        return f"'{escaped_value}'"

    def load_existing_env(self) -> bool:
        """Load existing .env file if it exists, or fall back to environment variables.
        
        Uses python-dotenv's load_dotenv() for standard .env file parsing, which handles:
        - Quoted values (single and double quotes)
        - Variable expansion (${VAR})
        - Multiline values
        - Escaped characters
        - Comments
        """
        # Map env vars to config attributes
        # These are environment variable names, not actual secrets
        attr_map = {  # pragma: allowlist secret
            "OPENAI_API_KEY": "openai_api_key",  # pragma: allowlist secret
            "ANTHROPIC_API_KEY": "anthropic_api_key",  # pragma: allowlist secret
            "OLLAMA_ENDPOINT": "ollama_endpoint",
            "WATSONX_API_KEY": "watsonx_api_key",  # pragma: allowlist secret
            "WATSONX_ENDPOINT": "watsonx_endpoint",
            "WATSONX_PROJECT_ID": "watsonx_project_id",
            "OPENSEARCH_PASSWORD": "opensearch_password",  # pragma: allowlist secret
            "OPENSEARCH_USERNAME": "opensearch_username",
            "OPENSEARCH_HOST": "opensearch_host",
            "OPENSEARCH_PORT": "opensearch_port",
            "OPENSEARCH_INDEX_NAME": "opensearch_index_name",
            "LANGFLOW_SECRET_KEY": "langflow_secret_key",  # pragma: allowlist secret
            "LANGFLOW_SUPERUSER": "langflow_superuser",
            "LANGFLOW_SUPERUSER_PASSWORD": "langflow_superuser_password",  # pragma: allowlist secret
            "LANGFLOW_CHAT_FLOW_ID": "langflow_chat_flow_id",
            "LANGFLOW_INGEST_FLOW_ID": "langflow_ingest_flow_id",
            "LANGFLOW_URL_INGEST_FLOW_ID": "langflow_url_ingest_flow_id",
            "NUDGES_FLOW_ID": "nudges_flow_id",
            "GOOGLE_OAUTH_CLIENT_ID": "google_oauth_client_id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "google_oauth_client_secret",  # pragma: allowlist secret
            "MICROSOFT_GRAPH_OAUTH_CLIENT_ID": "microsoft_graph_oauth_client_id",
            "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET": "microsoft_graph_oauth_client_secret",  # pragma: allowlist secret
            "WEBHOOK_BASE_URL": "webhook_base_url",
            "AWS_ACCESS_KEY_ID": "aws_access_key_id",
            "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",  # pragma: allowlist secret
            "LANGFLOW_PUBLIC_URL": "langflow_public_url",
            "OPENRAG_DOCUMENTS_PATHS": "openrag_documents_paths",
            "OPENRAG_DOCUMENTS_PATH": "openrag_documents_path",
            "OPENRAG_KEYS_PATH": "openrag_keys_path",
            "OPENRAG_FLOWS_PATH": "openrag_flows_path",
            "OPENRAG_CONFIG_PATH": "openrag_config_path",
            "OPENRAG_DATA_PATH": "openrag_data_path",
            "OPENSEARCH_DATA_PATH": "opensearch_data_path",
            "LANGFLOW_AUTO_LOGIN": "langflow_auto_login",
            "LANGFLOW_NEW_USER_IS_ACTIVE": "langflow_new_user_is_active",
            "LANGFLOW_ENABLE_SUPERUSER_CLI": "langflow_enable_superuser_cli",
            "DISABLE_INGEST_WITH_LANGFLOW": "disable_ingest_with_langflow",
            "INGEST_SAMPLE_DATA": "ingest_sample_data",
            "OPENRAG_VERSION": "openrag_version",
            "LANGFUSE_SECRET_KEY": "langfuse_secret_key",  # pragma: allowlist secret
            "LANGFUSE_PUBLIC_KEY": "langfuse_public_key",  # pragma: allowlist secret
            "LANGFUSE_HOST": "langfuse_host",
        }
        
        loaded_from_file = False
        
        # Load .env file using python-dotenv for standard parsing
        # override=True ensures .env file values take precedence over existing environment variables
        if self.env_file.exists():
            try:
                # Load .env file with override=True to ensure file values take precedence
                load_dotenv(dotenv_path=self.env_file, override=True)
                loaded_from_file = True
                logger.debug(f"Loaded .env file from {self.env_file}")
            except Exception as e:
                logger.error("Error loading .env file", error=str(e))
        
        # Map environment variables to config attributes
        # This works whether values came from .env file or existing environment variables
        for env_key, attr_name in attr_map.items():
            value = os.environ.get(env_key, "")
            if value:
                setattr(self.config, attr_name, value)
        
        return loaded_from_file

    def setup_secure_defaults(self) -> None:
        """Set up secure default values for passwords and keys."""
        if not self.config.opensearch_password:
            self.config.opensearch_password = self.generate_secure_password()

        if not self.config.langflow_secret_key:
            self.config.langflow_secret_key = self.generate_langflow_secret_key()
        
        # Set OPENRAG_VERSION to TUI version if not already set
        if not self.config.openrag_version:
            try:
                from ..utils.version_check import get_current_version
                current_version = get_current_version()
                if current_version != "unknown":
                    self.config.openrag_version = current_version
            except Exception:
                # If we can't get version, leave it empty (will use 'latest' from compose)
                pass

        # Configure autologin based on whether password is set
        if not self.config.langflow_superuser_password:
            # If no password is set, enable autologin mode
            self.config.langflow_auto_login = "True"
            self.config.langflow_new_user_is_active = "True"
            self.config.langflow_enable_superuser_cli = "True"
        else:
            # If password is set, disable autologin mode
            self.config.langflow_auto_login = "False"
            self.config.langflow_new_user_is_active = "False"
            self.config.langflow_enable_superuser_cli = "False"

    def validate_config(self, mode: str = "full") -> bool:
        """
        Validate the current configuration.

        Args:
            mode: "no_auth" for minimal validation, "full" for complete validation
        """
        self.config.validation_errors.clear()

        # OpenAI API key is now optional (can be provided during onboarding)
        # Only validate format if a key is provided
        if self.config.openai_api_key and not validate_openai_api_key(self.config.openai_api_key):
            self.config.validation_errors["openai_api_key"] = (
                "Invalid OpenAI API key format (should start with sk-)"
            )

        # Import validation functions for new provider fields
        from ..utils.validation import validate_anthropic_api_key

        # Validate Anthropic API key format if provided
        if self.config.anthropic_api_key:
            if not validate_anthropic_api_key(self.config.anthropic_api_key):
                self.config.validation_errors["anthropic_api_key"] = (
                    "Invalid Anthropic API key format (should start with sk-ant-)"
                )

        # Validate Ollama endpoint if provided
        if self.config.ollama_endpoint:
            if not validate_url(self.config.ollama_endpoint):
                self.config.validation_errors["ollama_endpoint"] = (
                    "Invalid Ollama endpoint URL format"
                )

        # Validate IBM watsonx.ai endpoint if provided
        if self.config.watsonx_endpoint:
            if not validate_url(self.config.watsonx_endpoint):
                self.config.validation_errors["watsonx_endpoint"] = (
                    "Invalid IBM watsonx.ai endpoint URL format"
                )

        # Validate documents paths only if provided (optional)
        if self.config.openrag_documents_paths:
            is_valid, error_msg, _ = validate_documents_paths(
                self.config.openrag_documents_paths
            )
            if not is_valid:
                self.config.validation_errors["openrag_documents_paths"] = error_msg

        # Validate required fields
        if not validate_non_empty(self.config.opensearch_password):
            self.config.validation_errors["opensearch_password"] = (
                "OpenSearch password is required"
            )

        # Langflow secret key is auto-generated; no user input required

        # Langflow password is now optional - if not provided, autologin mode will be enabled

        if mode == "full":
            # Validate OAuth settings if provided
            if (
                self.config.google_oauth_client_id
                and not validate_google_oauth_client_id(
                    self.config.google_oauth_client_id
                )
            ):
                self.config.validation_errors["google_oauth_client_id"] = (
                    "Invalid Google OAuth client ID format"
                )

            if self.config.google_oauth_client_id and not validate_non_empty(
                self.config.google_oauth_client_secret
            ):
                self.config.validation_errors["google_oauth_client_secret"] = (
                    "Google OAuth client secret required when client ID is provided"
                )

            if self.config.microsoft_graph_oauth_client_id and not validate_non_empty(
                self.config.microsoft_graph_oauth_client_secret
            ):
                self.config.validation_errors["microsoft_graph_oauth_client_secret"] = (
                    "Microsoft Graph client secret required when client ID is provided"
                )

            # Validate optional URLs if provided
            if self.config.webhook_base_url and not validate_url(
                self.config.webhook_base_url
            ):
                self.config.validation_errors["webhook_base_url"] = (
                    "Invalid webhook URL format"
                )

            if self.config.langflow_public_url and not validate_url(
                self.config.langflow_public_url
            ):
                self.config.validation_errors["langflow_public_url"] = (
                    "Invalid Langflow public URL format"
                )

        return len(self.config.validation_errors) == 0

    def save_env_file(self) -> bool:
        """Save current configuration to .env file."""
        try:
            # Ensure secure defaults (including Langflow secret key) are set before saving
            self.setup_secure_defaults()
            # Create timestamped backup if file exists
            if self.env_file.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = self.env_file.with_suffix(f".env.backup.{timestamp}")
                self.env_file.rename(backup_file)

            with open(self.env_file, "w") as f:
                f.write("# OpenRAG Environment Configuration\n")
                f.write("# Generated by OpenRAG TUI\n\n")

                # Core settings
                f.write("# Core settings\n")
                f.write(f"LANGFLOW_SECRET_KEY={self._quote_env_value(self.config.langflow_secret_key)}\n")
                # Only write LANGFLOW_SUPERUSER and password if password is set
                if self.config.langflow_superuser_password:
                    f.write(f"LANGFLOW_SUPERUSER={self._quote_env_value(self.config.langflow_superuser)}\n")
                    f.write(
                        f"LANGFLOW_SUPERUSER_PASSWORD={self._quote_env_value(self.config.langflow_superuser_password)}\n"
                    )
                f.write(f"LANGFLOW_CHAT_FLOW_ID={self._quote_env_value(self.config.langflow_chat_flow_id)}\n")
                f.write(
                    f"LANGFLOW_INGEST_FLOW_ID={self._quote_env_value(self.config.langflow_ingest_flow_id)}\n"
                )
                f.write(f"LANGFLOW_URL_INGEST_FLOW_ID={self._quote_env_value(self.config.langflow_url_ingest_flow_id)}\n")
                f.write(f"NUDGES_FLOW_ID={self._quote_env_value(self.config.nudges_flow_id)}\n")
                f.write(f"OPENSEARCH_PASSWORD={self._quote_env_value(self.config.opensearch_password)}\n")
                if self.config.opensearch_username and self.config.opensearch_username != "admin":
                    f.write(f"OPENSEARCH_USERNAME={self._quote_env_value(self.config.opensearch_username)}\n")
                if self.config.opensearch_host and self.config.opensearch_host != "opensearch":
                    f.write(f"OPENSEARCH_HOST={self._quote_env_value(self.config.opensearch_host)}\n")
                if self.config.opensearch_port and self.config.opensearch_port != "9200":
                    f.write(f"OPENSEARCH_PORT={self._quote_env_value(self.config.opensearch_port)}\n")
                f.write(f"OPENSEARCH_INDEX_NAME={self._quote_env_value(self.config.opensearch_index_name)}\n")

                # Expand $HOME in paths before writing to .env
                # This ensures paths work with all compose implementations (docker, podman)
                from utils.paths import expand_path
                f.write(
                    f"OPENRAG_DOCUMENTS_PATHS={self._quote_env_value(expand_path(self.config.openrag_documents_paths))}\n"
                )
                f.write("\n")

                # Volume mount paths for Docker Compose
                f.write("# Volume mount paths for Docker Compose\n")
                f.write(
                    f"OPENRAG_DOCUMENTS_PATH={self._quote_env_value(expand_path(self.config.openrag_documents_path))}\n"
                )
                f.write(
                    f"OPENRAG_KEYS_PATH={self._quote_env_value(expand_path(self.config.openrag_keys_path))}\n"
                )
                f.write(
                    f"OPENRAG_FLOWS_PATH={self._quote_env_value(expand_path(self.config.openrag_flows_path))}\n"
                )
                f.write(
                    f"OPENRAG_CONFIG_PATH={self._quote_env_value(expand_path(self.config.openrag_config_path))}\n"
                )
                f.write(
                    f"OPENRAG_DATA_PATH={self._quote_env_value(expand_path(self.config.openrag_data_path))}\n"
                )
                f.write(
                    f"OPENSEARCH_DATA_PATH={self._quote_env_value(expand_path(self.config.opensearch_data_path))}\n"
                )
                # Set OPENRAG_VERSION to TUI version
                if self.config.openrag_version:
                    f.write(f"OPENRAG_VERSION={self._quote_env_value(self.config.openrag_version)}\n")
                else:
                    # Fallback: try to get current version
                    try:
                        from ..utils.version_check import get_current_version
                        current_version = get_current_version()
                        if current_version != "unknown":
                            f.write(f"OPENRAG_VERSION={self._quote_env_value(current_version)}\n")
                    except Exception:
                        pass
                f.write("\n")

                # Provider API keys and endpoints (optional - can be set during onboarding)
                provider_vars = []
                if self.config.openai_api_key:
                    provider_vars.append(("OPENAI_API_KEY", self.config.openai_api_key))
                if self.config.anthropic_api_key:
                    provider_vars.append(("ANTHROPIC_API_KEY", self.config.anthropic_api_key))
                if self.config.ollama_endpoint:
                    provider_vars.append(("OLLAMA_ENDPOINT", self.config.ollama_endpoint))
                if self.config.watsonx_api_key:
                    provider_vars.append(("WATSONX_API_KEY", self.config.watsonx_api_key))
                if self.config.watsonx_endpoint:
                    provider_vars.append(("WATSONX_ENDPOINT", self.config.watsonx_endpoint))
                if self.config.watsonx_project_id:
                    provider_vars.append(("WATSONX_PROJECT_ID", self.config.watsonx_project_id))
                
                if provider_vars:
                    f.write("# AI Provider API Keys and Endpoints\n")
                    for var_name, var_value in provider_vars:
                        f.write(f"{var_name}={self._quote_env_value(var_value)}\n")
                    f.write("\n")

                # Ingestion settings
                f.write("# Ingestion settings\n")
                f.write(f"DISABLE_INGEST_WITH_LANGFLOW={self._quote_env_value(self.config.disable_ingest_with_langflow)}\n")
                f.write(f"INGEST_SAMPLE_DATA={self._quote_env_value(self.config.ingest_sample_data)}\n")
                f.write("\n")

                # Langflow auth settings
                f.write("# Langflow auth settings\n")
                f.write(f"LANGFLOW_AUTO_LOGIN={self._quote_env_value(self.config.langflow_auto_login)}\n")
                f.write(
                    f"LANGFLOW_NEW_USER_IS_ACTIVE={self._quote_env_value(self.config.langflow_new_user_is_active)}\n"
                )
                f.write(
                    f"LANGFLOW_ENABLE_SUPERUSER_CLI={self._quote_env_value(self.config.langflow_enable_superuser_cli)}\n"
                )
                f.write("\n")

                # OAuth settings
                if (
                    self.config.google_oauth_client_id
                    or self.config.google_oauth_client_secret
                ):
                    f.write("# Google OAuth settings\n")
                    f.write(
                        f"GOOGLE_OAUTH_CLIENT_ID={self._quote_env_value(self.config.google_oauth_client_id)}\n"
                    )
                    f.write(
                        f"GOOGLE_OAUTH_CLIENT_SECRET={self._quote_env_value(self.config.google_oauth_client_secret)}\n"
                    )
                    f.write("\n")

                if (
                    self.config.microsoft_graph_oauth_client_id
                    or self.config.microsoft_graph_oauth_client_secret
                ):
                    f.write("# Microsoft Graph OAuth settings\n")
                    f.write(
                        f"MICROSOFT_GRAPH_OAUTH_CLIENT_ID={self._quote_env_value(self.config.microsoft_graph_oauth_client_id)}\n"
                    )
                    f.write(
                        f"MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET={self._quote_env_value(self.config.microsoft_graph_oauth_client_secret)}\n"
                    )
                    f.write("\n")

                # Optional settings
                optional_vars = [
                    ("WEBHOOK_BASE_URL", self.config.webhook_base_url),
                    ("AWS_ACCESS_KEY_ID", self.config.aws_access_key_id),
                    ("AWS_SECRET_ACCESS_KEY", self.config.aws_secret_access_key),
                    ("LANGFLOW_PUBLIC_URL", self.config.langflow_public_url),
                ]

                optional_written = False
                for var_name, var_value in optional_vars:
                    if var_value:
                        if not optional_written:
                            f.write("# Optional settings\n")
                            optional_written = True
                        f.write(f"{var_name}={self._quote_env_value(var_value)}\n")

                if optional_written:
                    f.write("\n")

                # Langfuse settings (optional)
                langfuse_vars = [
                    ("LANGFUSE_SECRET_KEY", self.config.langfuse_secret_key),
                    ("LANGFUSE_PUBLIC_KEY", self.config.langfuse_public_key),
                    ("LANGFUSE_HOST", self.config.langfuse_host),
                ]

                langfuse_written = False
                for var_name, var_value in langfuse_vars:
                    if var_value:
                        if not langfuse_written:
                            f.write("# Langfuse settings\n")
                            langfuse_written = True
                        f.write(f"{var_name}={self._quote_env_value(var_value)}\n")

                if langfuse_written:
                    f.write("\n")

            return True

        except Exception as e:
            logger.error("Error saving .env file", error=str(e))
            return False

    def get_no_auth_setup_fields(self) -> List[tuple[str, str, str, bool]]:
        """Get fields required for no-auth setup mode. Returns (field_name, display_name, placeholder, can_generate)."""
        return [
            ("openai_api_key", "OpenAI API Key", "sk-... or leave empty", False),
            (
                "opensearch_password",
                "OpenSearch Password",
                "Will be auto-generated if empty",
                True,
            ),
            (
                "langflow_superuser_password",
                "Langflow Superuser Password",
                "Will be auto-generated if empty",
                True,
            ),
            (
                "openrag_documents_paths",
                "Documents Paths",
                "~/.openrag/documents",
                False,
            ),
        ]

    def get_full_setup_fields(self) -> List[tuple[str, str, str, bool]]:
        """Get all fields for full setup mode."""
        base_fields = self.get_no_auth_setup_fields()

        oauth_fields = [
            (
                "google_oauth_client_id",
                "Google OAuth Client ID",
                "xxx.apps.googleusercontent.com",
                False,
            ),
            ("google_oauth_client_secret", "Google OAuth Client Secret", "", False),
            ("microsoft_graph_oauth_client_id", "Microsoft Graph Client ID", "", False),
            (
                "microsoft_graph_oauth_client_secret",
                "Microsoft Graph Client Secret",
                "",
                False,
            ),
        ]

        flow_fields = [
            (
                "nudges_flow_id",
                "Nudges Flow ID",
                "ebc01d31-1976-46ce-a385-b0240327226c",
                False,
            ),
        ]

        optional_fields = [
            (
                "disable_ingest_with_langflow",
                "Disable Langflow Ingestion (optional)",
                "False",
                False,
            ),
            (
                "ingest_sample_data",
                "Ingest Sample Data (optional)",
                "True",
                False,
            ),
            (
                "opensearch_index_name",
                "OpenSearch Index Name",
                "documents",
                False,
            ),
            (
                "webhook_base_url",
                "Webhook Base URL (optional)",
                "https://your-domain.com",
                False,
            ),
            ("aws_access_key_id", "AWS Access Key ID (optional)", "", False),
            ("aws_secret_access_key", "AWS Secret Access Key (optional)", "", False),
            (
                "langflow_public_url",
                "Langflow Public URL (optional)",
                "http://localhost:7860",
                False,
            ),
        ]

        return base_fields + oauth_fields + flow_fields + optional_fields

    def ensure_openrag_version(self) -> None:
        """Ensure OPENRAG_VERSION is set in .env file to match TUI version."""
        try:
            from ..utils.version_check import get_current_version
            import os
            current_version = get_current_version()
            if current_version == "unknown":
                return
            
            # Check if OPENRAG_VERSION is already set in .env
            if self.env_file.exists():
                # Load .env file using load_dotenv
                load_dotenv(dotenv_path=self.env_file, override=False)
                existing_value = os.environ.get("OPENRAG_VERSION", "")
                if existing_value and existing_value == current_version:
                    # Already correct, no update needed
                    return
            
            # Set or update OPENRAG_VERSION
            self.config.openrag_version = current_version
            
            # Update .env file
            if self.env_file.exists():
                # Read existing content
                lines = self.env_file.read_text().splitlines()
                updated = False
                new_lines = []
                
                for line in lines:
                    if line.strip().startswith("OPENRAG_VERSION"):
                        # Replace existing line
                        new_lines.append(f"OPENRAG_VERSION={self._quote_env_value(current_version)}")
                        updated = True
                    else:
                        new_lines.append(line)
                
                # If not found, add it after OPENSEARCH_DATA_PATH or at the end
                if not updated:
                    insert_pos = len(new_lines)
                    for i, line in enumerate(new_lines):
                        if "OPENSEARCH_DATA_PATH" in line:
                            insert_pos = i + 1
                            break
                    new_lines.insert(insert_pos, f"OPENRAG_VERSION={self._quote_env_value(current_version)}")
                
                with open(self.env_file, 'w') as f:
                    f.write("\n".join(new_lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            else:
                # Create new .env file with just OPENRAG_VERSION
                with open(self.env_file, 'w') as f:
                    content = (
                        f"# OpenRAG Environment Configuration\n"
                        f"# Generated by OpenRAG TUI\n\n"
                        f"OPENRAG_VERSION={self._quote_env_value(current_version)}\n"
                    )
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
        except Exception as e:
            logger.debug(f"Error ensuring OPENRAG_VERSION: {e}")

    def generate_compose_volume_mounts(self) -> List[str]:
        """Generate Docker Compose volume mount strings from documents paths."""
        # Expand $HOME before validation
        paths_str = self.config.openrag_documents_paths.replace("$HOME", str(Path.home()))
        is_valid, error_msg, validated_paths = validate_documents_paths(paths_str)

        if not is_valid:
            logger.warning(f"Invalid documents paths: {error_msg}")
            return []

        volume_mounts = []
        for i, path in enumerate(validated_paths):
            if i == 0:
                # First path maps to the default /app/openrag-documents
                volume_mounts.append(f"{path}:/app/openrag-documents:Z")
            else:
                # Additional paths map to numbered directories
                volume_mounts.append(f"{path}:/app/openrag-documents{i + 1}:Z")

        return volume_mounts
