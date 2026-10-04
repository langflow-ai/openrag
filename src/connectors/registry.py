"""Registry of available connector classes.

Combines the builtin OSS connectors with any extras contributed by the
top-level `enhancements/` package (loaded best-effort — absence is fine).

Shared code (`connection_manager`, settings endpoints, etc.) should look up
connector classes via this module instead of hard-coding imports/branches.
"""
import inspect
import os
import re
from importlib.metadata import entry_points

from .aws_s3 import S3Connector
from .base import BaseConnector
from .google_drive import GoogleDriveConnector
from .onedrive import OneDriveConnector
from .sharepoint import SharePointConnector

# Connector classes shipped with OSS. Enhancements retain their existing
# best-effort loading behavior; customer wheels are a separate opt-in seam.
BUILTIN_CONNECTORS: list[type[BaseConnector]] = [
    GoogleDriveConnector,
    OneDriveConnector,
    SharePointConnector,
    S3Connector,
]

PLUGIN_ENTRY_POINT_GROUP = "openrag.connectors.v1"
_plugin_connectors: tuple[type[BaseConnector], ...] | None = None
_PLUGIN_TYPE = re.compile(r"[a-z][a-z0-9_]*\Z")


def _load_plugins() -> tuple[type[BaseConnector], ...]:
    """Resolve the operator allowlist once; disabled wheels are never imported."""
    global _plugin_connectors
    if _plugin_connectors is not None:
        return _plugin_connectors

    allowed = {name.strip() for name in os.getenv("OPENRAG_CONNECTOR_PLUGINS", "").split(",") if name.strip()}
    if not allowed:
        _plugin_connectors = ()
        return _plugin_connectors

    existing = {cls.CONNECTOR_TYPE for cls in BUILTIN_CONNECTORS + _load_additional()}
    points = entry_points().select(group=PLUGIN_ENTRY_POINT_GROUP)
    selected: dict[str, list] = {name: [] for name in allowed}
    for point in points:
        if point.name in selected:
            selected[point.name].append(point)

    plugins: list[type[BaseConnector]] = []
    for name in sorted(allowed):
        if not _PLUGIN_TYPE.fullmatch(name):
            raise RuntimeError(f"Invalid OPENRAG_CONNECTOR_PLUGINS entry {name!r}: use lowercase connector types")
        matches = selected[name]
        if not matches:
            raise RuntimeError(
                f"Enabled connector plugin {name!r} not installed: install its wheel with "
                f"an {PLUGIN_ENTRY_POINT_GROUP} entry point, or remove it from OPENRAG_CONNECTOR_PLUGINS"
            )
        if len(matches) != 1:
            raise RuntimeError(f"Duplicate {PLUGIN_ENTRY_POINT_GROUP} entry points for enabled connector {name!r}")
        if name in existing:
            raise RuntimeError(f"Connector plugin {name!r} collides with a built-in or enhancement connector")

        try:
            cls = matches[0].load()
        except Exception as exc:
            raise RuntimeError(f"Failed to load enabled connector plugin {name!r} from {matches[0].value}") from exc
        if not isinstance(cls, type) or not issubclass(cls, BaseConnector):
            raise RuntimeError(f"Connector plugin {name!r} must export a BaseConnector subclass")
        if cls.CONNECTOR_TYPE != name or cls.CONNECTOR_KIND != "bucket":
            raise RuntimeError(f"Connector plugin {name!r} must declare CONNECTOR_TYPE={name!r} and CONNECTOR_KIND='bucket'")
        if type(getattr(cls, "CONNECTOR_API_VERSION", None)) is not int or cls.CONNECTOR_API_VERSION != 1:
            raise RuntimeError(
                f"Connector plugin {name!r} must declare CONNECTOR_API_VERSION=1 "
                f"for {PLUGIN_ENTRY_POINT_GROUP}"
            )
        capability = getattr(cls, "BROWSE_CAPABILITY", None)
        if (
            inspect.isabstract(cls)
            or capability not in ("hierarchical", "flat")
            or (capability == "hierarchical" and not callable(getattr(cls, "list_children", None)))
        ):
            raise RuntimeError(
                f"Connector plugin {name!r} requires a concrete BaseConnector with "
                "BROWSE_CAPABILITY='flat' or hierarchical list_children"
            )
        fields = plugin_config_fields(cls)  # Validate before exposing anything to HTTP clients.
        pair = getattr(cls, "CREDENTIAL_PAIR", None)
        if pair is not None and (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or pair[0] == pair[1]
            or not all(
                any(field["name"] == key and field["type"] == "secret" for field in fields)
                for key in pair
            )
        ):
            raise RuntimeError(f"Invalid CREDENTIAL_PAIR in plugin {name!r}")
        existing.add(name)
        plugins.append(cls)
    _plugin_connectors = tuple(plugins)
    return _plugin_connectors


def plugin_config_fields(cls: type[BaseConnector]) -> list[dict[str, str | bool]]:
    """Return only safe form descriptors, rejecting malformed plugin contracts."""
    fields = getattr(cls, "CONFIG_FIELDS", None)
    if not isinstance(fields, (list, tuple)) or not fields:
        raise RuntimeError(f"Connector plugin {cls.CONNECTOR_TYPE!r} needs CONFIG_FIELDS")
    result = []
    names = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"name", "label", "type", "required"}:
            raise RuntimeError(f"Invalid CONFIG_FIELDS in plugin {cls.CONNECTOR_TYPE!r}")
        key, label, kind, required = (field[k] for k in ("name", "label", "type", "required"))
        if (
            not isinstance(key, str)
            or not _PLUGIN_TYPE.fullmatch(key)
            or key == "user_id"  # supplied only from authenticated connection ownership
            or key in names
            or not isinstance(label, str)
            or not label.strip()
            or kind not in ("text", "secret")
            or type(required) is not bool
        ):
            raise RuntimeError(f"Invalid CONFIG_FIELDS in plugin {cls.CONNECTOR_TYPE!r}")
        names.add(key)
        result.append({"name": key, "label": label, "type": kind, "required": required})
    return result


def get_plugin_connector_class(connector_type: str) -> type[BaseConnector] | None:
    return next((cls for cls in _load_plugins() if cls.CONNECTOR_TYPE == connector_type), None)


def is_plugin_connector_type(connector_type: str) -> bool:
    return get_plugin_connector_class(connector_type) is not None


def get_route_connector_classes() -> list[type[BaseConnector]]:
    """Only first-party/enhancement classes may register arbitrary API routes."""
    _load_plugins()  # startup validation
    return BUILTIN_CONNECTORS + _load_additional()


def get_plugin_secret_keys() -> set[str]:
    return {
        field["name"]
        for cls in _load_plugins()
        for field in plugin_config_fields(cls)
        if field["type"] == "secret"
    }


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
    return get_route_connector_classes() + list(_load_plugins())


def get_connector_class(connector_type: str) -> type[BaseConnector] | None:
    for cls in get_connector_classes():
        if cls.CONNECTOR_TYPE == connector_type:
            return cls
    return None


def get_all_secret_keys() -> set[str]:
    keys = set(GENERAL_SECRET_KEYS)
    for cls in get_route_connector_classes():
        keys.update(cls.SECRET_CONFIG_KEYS)
    return keys
