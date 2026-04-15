"""Shared config field definitions for TUI and CLI wizard.

This is the single source of truth for all user-configurable fields.
Both the TUI config screen and the CLI wizard consume these definitions.
"""

from dataclasses import dataclass, field as dataclass_field
from typing import Callable, Optional

from .utils.validation import (
    validate_openai_api_key,
    validate_anthropic_api_key,
    validate_ollama_endpoint,
    validate_watsonx_endpoint,
)


@dataclass
class ConfigField:
    """A single user-configurable field."""

    name: str  # attribute name on EnvConfig
    env_var: str  # environment variable name
    label: str  # display label
    placeholder: str = ""
    default: str = ""
    secret: bool = False
    required: bool = False
    advanced: bool = False  # only shown in full/advanced mode
    helper_text: str = ""
    validator: Optional[Callable[[str], bool]] = None
    validator_error: str = ""


@dataclass
class ConfigSection:
    """A group of related config fields."""

    name: str  # section header
    fields: list[ConfigField] = dataclass_field(default_factory=list)
    advanced: bool = False  # entire section is advanced-only
    gate_prompt: str = ""  # CLI y/N prompt to enter this section


CONFIG_SECTIONS: list[ConfigSection] = [
    # ── Security ────────────────────────────────────────────────
    ConfigSection("Security", [
        ConfigField(
            "openrag_encryption_key", "OPENRAG_ENCRYPTION_KEY", "OpenRAG Master Key",
            placeholder="Auto-generated secure Base64 key",
            secret=True, required=True,
            helper_text="32-byte Base64 key for securing your database credentials (auto-generates if empty)",
        ),
        ConfigField(
            "openrag_tenant_id", "OPENRAG_TENANT_ID", "Tenant ID",
            placeholder="openrag", default="openrag",
            helper_text="Identifier for AAD tenant binding (default: openrag)",
        ),
        ConfigField(
            "openrag_enforce_prerequisites", "OPENRAG_ENFORCE_PREREQUISITES", "Enforce Prerequisites",
            placeholder="false", default="false",
            advanced=True,
            helper_text="If true, application will fail to start if the encryption key is missing",
        ),
    ]),

    # ── OpenSearch ──────────────────────────────────────────────
    ConfigSection("OpenSearch", [
        ConfigField(
            "opensearch_password", "OPENSEARCH_PASSWORD", "Admin Password",
            placeholder="Auto-generated secure password",
            secret=True, required=True,
            helper_text="Validate your password here: https://lowe.github.io/tryzxcvbn/",
        ),
        ConfigField(
            "opensearch_username", "OPENSEARCH_USERNAME", "Admin Username",
            placeholder="admin", default="admin",
            helper_text="OpenSearch admin username (default: admin)",
        ),
        ConfigField(
            "opensearch_host", "OPENSEARCH_HOST", "Host",
            placeholder="opensearch", default="opensearch",
            helper_text="Override for remote OpenSearch instances (default: opensearch)",
        ),
        ConfigField(
            "opensearch_port", "OPENSEARCH_PORT", "Port",
            placeholder="9200", default="9200",
            helper_text="Override for remote OpenSearch instances (default: 9200)",
        ),
        ConfigField(
            "opensearch_index_name", "OPENSEARCH_INDEX_NAME", "Index Name",
            placeholder="documents", default="documents",
            helper_text="Name of the index to use in OpenSearch",
        ),
    ]),

    # ── Langflow ────────────────────────────────────────────────
    ConfigSection("Langflow", [
        ConfigField(
            "langflow_superuser_password", "LANGFLOW_SUPERUSER_PASSWORD",
            "Admin Password",
            placeholder="Langflow password", secret=True,
            helper_text="Leave empty for autologin (no password required)",
        ),
        ConfigField(
            "langflow_superuser", "LANGFLOW_SUPERUSER", "Admin Username",
            placeholder="admin", default="admin",
        ),
        ConfigField(
            "langflow_data_path", "LANGFLOW_DATA_PATH", "Data Path",
            placeholder="~/.openrag/data/langflow-data",
            default="$HOME/.openrag/data/langflow-data",
            helper_text="Directory to persist Langflow flows and state across restarts",
        ),
        ConfigField(
            "langflow_public_url", "LANGFLOW_PUBLIC_URL", "Public URL",
            placeholder="http://localhost:7860",
            helper_text="External URL for Langflow access",
            advanced=True,
        ),
    ]),

    # ── AI Providers ────────────────────────────────────────────
    ConfigSection("AI Providers", [
        ConfigField(
            "openai_api_key", "OPENAI_API_KEY", "OpenAI API Key",
            placeholder="sk-...", secret=True,
            helper_text="Get a key: https://platform.openai.com/api-keys",
            validator=validate_openai_api_key,
            validator_error="Invalid OpenAI API key format (should start with sk-)",
        ),
        ConfigField(
            "anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic API Key",
            placeholder="sk-ant-...", secret=True,
            helper_text="Get a key: https://console.anthropic.com/settings/keys",
            validator=validate_anthropic_api_key,
            validator_error="Invalid Anthropic API key format (should start with sk-ant-)",
        ),
        ConfigField(
            "ollama_endpoint", "OLLAMA_ENDPOINT", "Ollama Base URL",
            placeholder="http://localhost:11434",
            helper_text="Endpoint of your Ollama server",
            validator=validate_ollama_endpoint,
            validator_error="Invalid Ollama endpoint URL format",
        ),
        ConfigField(
            "watsonx_api_key", "WATSONX_API_KEY", "IBM watsonx.ai API Key",
            placeholder="", secret=True,
            helper_text="Get a key: https://cloud.ibm.com/iam/apikeys",
        ),
        ConfigField(
            "watsonx_endpoint", "WATSONX_ENDPOINT", "IBM watsonx.ai Endpoint",
            placeholder="https://us-south.ml.cloud.ibm.com",
            helper_text="Example: https://us-south.ml.cloud.ibm.com",
            validator=validate_watsonx_endpoint,
            validator_error="Invalid watsonx.ai endpoint URL format",
        ),
        ConfigField(
            "watsonx_project_id", "WATSONX_PROJECT_ID", "IBM watsonx.ai Project ID",
            placeholder="",
            helper_text="Find in your IBM Cloud project settings",
        ),
    ]),

    # ── Google OAuth ────────────────────────────────────────────
    ConfigSection("Google OAuth", [
        ConfigField(
            "google_oauth_client_id", "GOOGLE_OAUTH_CLIENT_ID", "Client ID",
            placeholder="xxx.apps.googleusercontent.com",
            helper_text="Create credentials: https://console.cloud.google.com/apis/credentials",
        ),
        ConfigField(
            "google_oauth_client_secret", "GOOGLE_OAUTH_CLIENT_SECRET",
            "Client Secret",
            placeholder="", secret=True,
        ),
    ], advanced=True, gate_prompt="Configure Google OAuth?"),

    # ── Microsoft Graph OAuth ───────────────────────────────────
    ConfigSection("Microsoft Graph OAuth", [
        ConfigField(
            "microsoft_graph_oauth_client_id", "MICROSOFT_GRAPH_OAUTH_CLIENT_ID",
            "Client ID",
            placeholder="",
            helper_text="Create app: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        ),
        ConfigField(
            "microsoft_graph_oauth_client_secret",
            "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET", "Client Secret",
            placeholder="", secret=True,
        ),
    ], advanced=True, gate_prompt="Configure Microsoft Graph OAuth?"),

    # ── AWS ─────────────────────────────────────────────────────
    ConfigSection("AWS", [
        ConfigField(
            "aws_access_key_id", "AWS_ACCESS_KEY_ID", "Access Key ID",
            placeholder="",
            helper_text="Create keys: https://console.aws.amazon.com/iam/home#/security_credentials",
        ),
        ConfigField(
            "aws_secret_access_key", "AWS_SECRET_ACCESS_KEY", "Secret Access Key",
            placeholder="", secret=True,
        ),
        ConfigField(
            "aws_s3_endpoint", "AWS_S3_ENDPOINT", "S3 Endpoint URL (optional)",
            placeholder="",
            helper_text="Leave empty for AWS S3. For MinIO, R2, or other S3-compatible services, enter the endpoint URL.",
        ),
        ConfigField(
            "aws_region", "AWS_REGION", "AWS Region (optional)",
            placeholder="us-east-1",
            default="us-east-1",
            helper_text="AWS region (e.g. us-east-1, eu-west-1). Default: us-east-1.",
        ),
    ], advanced=True, gate_prompt="Configure AWS credentials?"),

    # ── IBM Cloud Object Storage ─────────────────────────────────
    ConfigSection("IBM Cloud Object Storage", [
        ConfigField(
            "ibm_cos_api_key", "IBM_COS_API_KEY", "API Key",
            placeholder="",
            helper_text="Create API key at https://cloud.ibm.com/iam/apikeys",
            secret=True,
        ),
        ConfigField(
            "ibm_cos_service_instance_id", "IBM_COS_SERVICE_INSTANCE_ID",
            "Service Instance ID (CRN)",
            placeholder="crn:v1:bluemix:...",
        ),
        ConfigField(
            "ibm_cos_endpoint", "IBM_COS_ENDPOINT", "Service Endpoint",
            placeholder="https://s3.us-south.cloud-object-storage.appdomain.cloud",
            helper_text="Endpoints: https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-endpoints",
        ),
        ConfigField(
            "ibm_cos_hmac_access_key_id", "IBM_COS_HMAC_ACCESS_KEY_ID",
            "HMAC Access Key ID (optional)",
            placeholder="",
        ),
        ConfigField(
            "ibm_cos_hmac_secret_access_key", "IBM_COS_HMAC_SECRET_ACCESS_KEY",
            "HMAC Secret Access Key (optional)",
            placeholder="", secret=True,
        ),
    ], advanced=True, gate_prompt="Configure IBM Cloud Object Storage?"),

    # ── Langfuse ────────────────────────────────────────────────
    ConfigSection("Langfuse", [
        ConfigField(
            "langfuse_secret_key", "LANGFUSE_SECRET_KEY", "Secret Key",
            placeholder="sk-lf-...", secret=True,
            helper_text="Get keys from your Langfuse project settings",
        ),
        ConfigField(
            "langfuse_public_key", "LANGFUSE_PUBLIC_KEY", "Public Key",
            placeholder="pk-lf-...", secret=True,
        ),
        ConfigField(
            "langfuse_host", "LANGFUSE_HOST", "Host",
            placeholder="https://cloud.langfuse.com",
            helper_text="Leave empty for Langfuse Cloud, or set for self-hosted",
        ),
    ], gate_prompt="Configure Langfuse tracing?"),

    # ── Storage ─────────────────────────────────────────────────
    ConfigSection("Storage", [
        ConfigField(
            "openrag_documents_paths", "OPENRAG_DOCUMENTS_PATHS", "Documents Paths",
            placeholder="~/.openrag/documents",
            default="$HOME/.openrag/documents",
            helper_text="Directories containing documents to ingest (comma-separated)",
        ),
    ]),

    # ── Advanced ────────────────────────────────────────────────
    ConfigSection("Advanced", [
        ConfigField(
            "webhook_base_url", "WEBHOOK_BASE_URL", "Webhook Base URL",
            placeholder="https://your-domain.com",
            helper_text="External URL for continuous ingestion webhooks",
        ),
    ], advanced=True),
]


def get_all_fields() -> list[ConfigField]:
    """Return a flat list of all config fields."""
    return [f for section in CONFIG_SECTIONS for f in section.fields]


def get_field(name: str) -> Optional[ConfigField]:
    """Look up a config field by attribute name."""
    for f in get_all_fields():
        if f.name == name:
            return f
    return None
