import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DocumentACL:
    """Access Control List information for a document"""

    owner: str = None
    allowed_users: list[str] = None
    allowed_groups: list[str] = None
    allowed_principals: list[str] = None
    allowed_principal_labels: list[dict[str, Any]] = None

    def __post_init__(self):
        if self.allowed_users is None:
            self.allowed_users = []
        if self.allowed_groups is None:
            self.allowed_groups = []
        if self.allowed_principals is None:
            self.allowed_principals = []
        if self.allowed_principal_labels is None:
            self.allowed_principal_labels = []


@dataclass
class ConnectorDocument:
    """Document from a connector with metadata"""

    id: str
    filename: str
    mimetype: str
    content: bytes
    source_url: str
    acl: DocumentACL
    modified_time: datetime
    created_time: datetime
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseConnector(ABC):
    """Base class for all document connectors"""

    # Each connector must define the environment variable names for OAuth credentials
    CLIENT_ID_ENV_VAR: str = None
    CLIENT_SECRET_ENV_VAR: str = None

    # Stable identifier used in connections.json and on the wire (e.g. "google_drive").
    CONNECTOR_TYPE: str = None
    # "oauth" connectors authenticate per-user via OAuth env-var credentials.
    # "bucket" connectors authenticate via per-connection config dict (HMAC, API key, etc).
    CONNECTOR_KIND: str = "oauth"
    # Connector-specific keys in the config dict that must be encrypted at rest.
    SECRET_CONFIG_KEYS: tuple = ()

    # Connector metadata for UI
    CONNECTOR_NAME: str = None
    CONNECTOR_DESCRIPTION: str = None
    CONNECTOR_ICON: str = None  # Icon identifier or emoji

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._authenticated = False

    @classmethod
    def register_routes(cls, app) -> None:
        """Register connector-specific FastAPI routes on the given app.

        Default: no-op. Connectors with extra endpoints (bucket listing,
        credential configuration, etc.) should override this and add their
        own `app.add_api_route(...)` calls.
        """
        return None

    @classmethod
    def is_available(cls, manager, user_id: str | None = None) -> bool:
        """Whether this connector should be offered to the given user.

        Default (oauth-kind): env credentials present OR user has a saved connection.
        Bucket-kind connectors should override to gate on their own feature flag.
        """
        try:
            instance = cls({})
            instance.get_client_id()
            instance.get_client_secret()
            return True
        except (ValueError, NotImplementedError, RuntimeError):
            return manager._has_saved_credentials_for_user(cls.CONNECTOR_TYPE, user_id)

    def get_client_id(self) -> str:
        """Get the OAuth client ID from environment variable"""
        if not self.CLIENT_ID_ENV_VAR:
            raise NotImplementedError(f"{self.__class__.__name__} must define CLIENT_ID_ENV_VAR")

        client_id = os.getenv(self.CLIENT_ID_ENV_VAR)
        if not client_id:
            raise ValueError(f"Environment variable {self.CLIENT_ID_ENV_VAR} is not set")

        return client_id

    def get_client_secret(self) -> str:
        """Get the OAuth client secret from environment variable"""
        if not self.CLIENT_SECRET_ENV_VAR:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define CLIENT_SECRET_ENV_VAR"
            )

        secret = os.getenv(self.CLIENT_SECRET_ENV_VAR)
        if not secret:
            raise ValueError(f"Environment variable {self.CLIENT_SECRET_ENV_VAR} is not set")

        return secret

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the service"""
        pass

    @abstractmethod
    async def setup_subscription(self) -> str:
        """Set up real-time subscription for file changes. Returns subscription ID."""
        pass

    @abstractmethod
    async def list_files(
        self, page_token: str | None = None, max_files: int | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """List all files. Returns files and next_page_token if any."""
        pass

    @abstractmethod
    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """Get file content and metadata"""
        pass

    @abstractmethod
    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        """Handle webhook notification. Returns list of affected file IDs."""
        pass

    def handle_webhook_validation(
        self, request_method: str, headers: dict[str, str], query_params: dict[str, str]
    ) -> str | None:
        """Handle webhook validation (e.g., for subscription setup).
        Returns validation response if applicable, None otherwise.
        Default implementation returns None (no validation needed)."""
        return None

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        """Extract channel/subscription ID from webhook payload/headers.
        Must be implemented by each connector."""
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement extract_webhook_channel_id"
        )

    @abstractmethod
    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """Clean up subscription"""
        pass

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    async def get_current_user_principal_labels(self) -> list[dict[str, Any]]:
        """Return non-authoritative display labels for current-user ACL principals."""
        return []

    async def _detect_base_url(self) -> str | None:
        """Auto-detect base URL for the connector.

        Default implementation returns None.
        Subclasses (OneDrive, SharePoint) should override this method.
        """
        return None

    async def get_current_user_group_roles(self) -> list[str]:
        """Return OpenSearch backend roles for the current connector user.

        Connectors that support upstream group ACLs can override this hook.
        The core ACL service calls it generically so new connectors only need
        to implement their own provider-specific group lookup.
        """
        return []

    async def get_current_user_principals(self) -> list[str]:
        """Return provider-scoped ACL principals for the current connector user.

        Connectors that store user ACLs in provider-specific identity spaces can
        override this hook. The DLS principal service calls it generically so new
        connectors only need to provide their own alias resolution.
        """
        return []

    @classmethod
    def get_auth_user_principals(cls, user: Any) -> list[str]:
        """Return connector principals derivable from the OpenRAG auth user.

        This hook covers cases where a document ACL names a provider user alias
        but the current OpenRAG user has no saved connector connection to query.
        Connectors should only return aliases when the auth provider gives enough
        information to construct the same principal used during ingestion.
        """
        return []
