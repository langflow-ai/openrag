"""Registry of available connector classes.

Combines the builtin OSS connectors with any extras contributed by the
top-level `enhancements/` package (loaded best-effort — absence is fine).

Shared code (`connection_manager`, settings endpoints, etc.) should look up
connector classes via this module instead of hard-coding imports/branches.
"""

from .aws_s3 import S3Connector
from .base import BaseConnector
from .google_drive import GoogleDriveConnector
from .onedrive import OneDriveConnector
from .sharepoint import SharePointConnector

# Connector classes shipped with OSS. Anything outside this list is contributed
# by the top-level `enhancements/` package (loaded best-effort).
BUILTIN_CONNECTORS: list[type[BaseConnector]] = [
    GoogleDriveConnector,
    OneDriveConnector,
    SharePointConnector,
    S3Connector,
]


# Config-dict secret keys that are not connector-specific (OAuth tokens, generic
# credentials shared across multiple connectors). Per-connector secret keys come
# from each class's SECRET_CONFIG_KEYS.
GENERAL_SECRET_KEYS = frozenset(
    {
        "api_key",
        "hmac_secret_key",
        "secret_key",
        "client_secret",
        "access_token",
        "refresh_token",
        "access_key",
        "hmac_access_key",
        "basic_credentials",
    }
)


def _load_additional() -> list[type[BaseConnector]]:
    try:
        from enhancements import ADDITIONAL_CONNECTORS
    except ModuleNotFoundError:
        # No enhancements package installed — bare OSS build.
        return []
    except Exception:
        import logging

        logging.getLogger(__name__).exception("ADDITIONAL_CONNECTORS import failed")
        raise
    return list(ADDITIONAL_CONNECTORS)


def get_connector_classes() -> list[type[BaseConnector]]:
    return BUILTIN_CONNECTORS + _load_additional()


def get_connector_class(connector_type: str) -> type[BaseConnector] | None:
    for cls in get_connector_classes():
        if cls.CONNECTOR_TYPE == connector_type:
            return cls
    return None


def get_all_secret_keys() -> set:
    keys = set(GENERAL_SECRET_KEYS)
    for cls in get_connector_classes():
        keys.update(cls.SECRET_CONFIG_KEYS)
    return keys
