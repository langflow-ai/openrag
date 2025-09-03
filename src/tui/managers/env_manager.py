"""Environment configuration manager for OpenRAG TUI."""

import os
import secrets
import string
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, field

from ..utils.validation import (
    validate_openai_api_key,
    validate_google_oauth_client_id,
    validate_non_empty,
    validate_url,
    validate_documents_paths,
    sanitize_env_value
)


@dataclass
class EnvConfig:
    """Environment configuration data."""
    # Core settings
    openai_api_key: str = ""
    opensearch_password: str = ""
    langflow_secret_key: str = ""
    langflow_superuser: str = "admin"
    langflow_superuser_password: str = ""
    flow_id: str = "1098eea1-6649-4e1d-aed1-b77249fb8dd0"
    
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
    
    # Document paths (comma-separated)
    openrag_documents_paths: str = "./documents"
    
    # Validation errors
    validation_errors: Dict[str, str] = field(default_factory=dict)


class EnvManager:
    """Manages environment configuration for OpenRAG."""
    
    def __init__(self, env_file: Optional[Path] = None):
        self.env_file = env_file or Path(".env")
        self.config = EnvConfig()
    
    def generate_secure_password(self) -> str:
        """Generate a secure password for OpenSearch."""
        # Generate a 16-character password with letters, digits, and symbols
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(16))
    
    def generate_langflow_secret_key(self) -> str:
        """Generate a secure secret key for Langflow."""
        return secrets.token_urlsafe(32)
    
    def load_existing_env(self) -> bool:
        """Load existing .env file if it exists."""
        if not self.env_file.exists():
            return False
        
        try:
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = sanitize_env_value(value)
                        
                        # Map env vars to config attributes
                        attr_map = {
                            'OPENAI_API_KEY': 'openai_api_key',
                            'OPENSEARCH_PASSWORD': 'opensearch_password',
                            'LANGFLOW_SECRET_KEY': 'langflow_secret_key',
                            'LANGFLOW_SUPERUSER': 'langflow_superuser',
                            'LANGFLOW_SUPERUSER_PASSWORD': 'langflow_superuser_password',
                            'FLOW_ID': 'flow_id',
                            'GOOGLE_OAUTH_CLIENT_ID': 'google_oauth_client_id',
                            'GOOGLE_OAUTH_CLIENT_SECRET': 'google_oauth_client_secret',
                            'MICROSOFT_GRAPH_OAUTH_CLIENT_ID': 'microsoft_graph_oauth_client_id',
                            'MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET': 'microsoft_graph_oauth_client_secret',
                            'WEBHOOK_BASE_URL': 'webhook_base_url',
                            'AWS_ACCESS_KEY_ID': 'aws_access_key_id',
                            'AWS_SECRET_ACCESS_KEY': 'aws_secret_access_key',
                            'LANGFLOW_PUBLIC_URL': 'langflow_public_url',
                            'OPENRAG_DOCUMENTS_PATHS': 'openrag_documents_paths',
                        }
                        
                        if key in attr_map:
                            setattr(self.config, attr_map[key], value)
            
            return True
            
        except Exception as e:
            print(f"Error loading .env file: {e}")
            return False
    
    def setup_secure_defaults(self) -> None:
        """Set up secure default values for passwords and keys."""
        if not self.config.opensearch_password:
            self.config.opensearch_password = self.generate_secure_password()
        
        if not self.config.langflow_secret_key:
            self.config.langflow_secret_key = self.generate_langflow_secret_key()
            
        if not self.config.langflow_superuser_password:
            self.config.langflow_superuser_password = self.generate_secure_password()
    
    def validate_config(self, mode: str = "full") -> bool:
        """
        Validate the current configuration.
        
        Args:
            mode: "no_auth" for minimal validation, "full" for complete validation
        """
        self.config.validation_errors.clear()
        
        # Always validate OpenAI API key
        if not validate_openai_api_key(self.config.openai_api_key):
            self.config.validation_errors['openai_api_key'] = "Invalid OpenAI API key format (should start with sk-)"
        
        # Validate documents paths only if provided (optional)
        if self.config.openrag_documents_paths:
            is_valid, error_msg, _ = validate_documents_paths(self.config.openrag_documents_paths)
            if not is_valid:
                self.config.validation_errors['openrag_documents_paths'] = error_msg
        
        # Validate required fields
        if not validate_non_empty(self.config.opensearch_password):
            self.config.validation_errors['opensearch_password'] = "OpenSearch password is required"
        
        # Langflow secret key is auto-generated; no user input required

        if not validate_non_empty(self.config.langflow_superuser_password):
            self.config.validation_errors['langflow_superuser_password'] = "Langflow superuser password is required"
        
        if mode == "full":
            # Validate OAuth settings if provided
            if self.config.google_oauth_client_id and not validate_google_oauth_client_id(self.config.google_oauth_client_id):
                self.config.validation_errors['google_oauth_client_id'] = "Invalid Google OAuth client ID format"
            
            if self.config.google_oauth_client_id and not validate_non_empty(self.config.google_oauth_client_secret):
                self.config.validation_errors['google_oauth_client_secret'] = "Google OAuth client secret required when client ID is provided"
            
            if self.config.microsoft_graph_oauth_client_id and not validate_non_empty(self.config.microsoft_graph_oauth_client_secret):
                self.config.validation_errors['microsoft_graph_oauth_client_secret'] = "Microsoft Graph client secret required when client ID is provided"
            
            # Validate optional URLs if provided
            if self.config.webhook_base_url and not validate_url(self.config.webhook_base_url):
                self.config.validation_errors['webhook_base_url'] = "Invalid webhook URL format"
            
            if self.config.langflow_public_url and not validate_url(self.config.langflow_public_url):
                self.config.validation_errors['langflow_public_url'] = "Invalid Langflow public URL format"
        
        return len(self.config.validation_errors) == 0
    
    def save_env_file(self) -> bool:
        """Save current configuration to .env file."""
        try:
            # Ensure secure defaults (including Langflow secret key) are set before saving
            self.setup_secure_defaults()
            # Create backup if file exists
            if self.env_file.exists():
                backup_file = self.env_file.with_suffix('.env.backup')
                self.env_file.rename(backup_file)
            
            with open(self.env_file, 'w') as f:
                f.write("# OpenRAG Environment Configuration\n")
                f.write("# Generated by OpenRAG TUI\n\n")
                
                # Core settings
                f.write("# Core settings\n")
                f.write(f"LANGFLOW_SECRET_KEY={self.config.langflow_secret_key}\n")
                f.write(f"LANGFLOW_SUPERUSER={self.config.langflow_superuser}\n")
                f.write(f"LANGFLOW_SUPERUSER_PASSWORD={self.config.langflow_superuser_password}\n")
                f.write(f"FLOW_ID={self.config.flow_id}\n")
                f.write(f"OPENSEARCH_PASSWORD={self.config.opensearch_password}\n")
                f.write(f"OPENAI_API_KEY={self.config.openai_api_key}\n")
                f.write(f"OPENRAG_DOCUMENTS_PATHS={self.config.openrag_documents_paths}\n")
                f.write("\n")
                
                # OAuth settings
                if self.config.google_oauth_client_id or self.config.google_oauth_client_secret:
                    f.write("# Google OAuth settings\n")
                    f.write(f"GOOGLE_OAUTH_CLIENT_ID={self.config.google_oauth_client_id}\n")
                    f.write(f"GOOGLE_OAUTH_CLIENT_SECRET={self.config.google_oauth_client_secret}\n")
                    f.write("\n")
                
                if self.config.microsoft_graph_oauth_client_id or self.config.microsoft_graph_oauth_client_secret:
                    f.write("# Microsoft Graph OAuth settings\n")
                    f.write(f"MICROSOFT_GRAPH_OAUTH_CLIENT_ID={self.config.microsoft_graph_oauth_client_id}\n")
                    f.write(f"MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET={self.config.microsoft_graph_oauth_client_secret}\n")
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
                        f.write(f"{var_name}={var_value}\n")
                
                if optional_written:
                    f.write("\n")
            
            return True
            
        except Exception as e:
            print(f"Error saving .env file: {e}")
            return False
    
    def get_no_auth_setup_fields(self) -> List[tuple[str, str, str, bool]]:
        """Get fields required for no-auth setup mode. Returns (field_name, display_name, placeholder, can_generate)."""
        return [
            ("openai_api_key", "OpenAI API Key", "sk-...", False),
            ("opensearch_password", "OpenSearch Password", "Will be auto-generated if empty", True),
            ("langflow_superuser_password", "Langflow Superuser Password", "Will be auto-generated if empty", True),
            ("openrag_documents_paths", "Documents Paths", "./documents,/path/to/more/docs", False),
        ]
    
    def get_full_setup_fields(self) -> List[tuple[str, str, str, bool]]:
        """Get all fields for full setup mode."""
        base_fields = self.get_no_auth_setup_fields()
        
        oauth_fields = [
            ("google_oauth_client_id", "Google OAuth Client ID", "xxx.apps.googleusercontent.com", False),
            ("google_oauth_client_secret", "Google OAuth Client Secret", "", False),
            ("microsoft_graph_oauth_client_id", "Microsoft Graph Client ID", "", False),
            ("microsoft_graph_oauth_client_secret", "Microsoft Graph Client Secret", "", False),
        ]
        
        optional_fields = [
            ("webhook_base_url", "Webhook Base URL (optional)", "https://your-domain.com", False),
            ("aws_access_key_id", "AWS Access Key ID (optional)", "", False),
            ("aws_secret_access_key", "AWS Secret Access Key (optional)", "", False),
            ("langflow_public_url", "Langflow Public URL (optional)", "http://localhost:7860", False),
        ]
        
        return base_fields + oauth_fields + optional_fields
    
    def generate_compose_volume_mounts(self) -> List[str]:
        """Generate Docker Compose volume mount strings from documents paths."""
        is_valid, _, validated_paths = validate_documents_paths(self.config.openrag_documents_paths)
        
        if not is_valid:
            return ["./documents:/app/documents:Z"]  # fallback
        
        volume_mounts = []
        for i, path in enumerate(validated_paths):
            if i == 0:
                # First path maps to the default /app/documents
                volume_mounts.append(f"{path}:/app/documents:Z")
            else:
                # Additional paths map to numbered directories
                volume_mounts.append(f"{path}:/app/documents{i+1}:Z")
        
        return volume_mounts
