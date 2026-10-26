"""Versioned, operator-enabled customer connector endpoints.

Only validated form descriptors and non-secret configuration cross back to the browser.
A plugin cannot register its own routes through this interface.
"""

import uuid
from typing import Any

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel

from connectors.connection_manager import ConnectionConfig
from connectors.registry import get_plugin_connector_class, plugin_config_fields
from dependencies import get_connector_service, get_session_manager, require_permission
from session_manager import User
from utils.encryption import encrypt_secret, get_master_secret
from utils.run_mode_utils import is_run_mode_saas


class PluginConfigBody(BaseModel):
    # Validate explicitly to avoid Pydantic's 422 response echoing credential input.
    config: Any = None
    connection_id: Any = None
    name: Any = None


async def _body(request: Request) -> PluginConfigBody:
    # FastAPI validation errors embed rejected input, including secrets.
    try:
        raw = await request.json()
    except ValueError:
        raise HTTPException(422, "Invalid connector configuration") from None
    if not isinstance(raw, dict):
        raise HTTPException(422, "Invalid connector configuration")
    return PluginConfigBody(
        config=raw.get("config"),
        connection_id=raw.get("connection_id"),
        name=raw.get("name"),
    )


def _plugin(connector_type: str):
    if is_run_mode_saas():
        raise HTTPException(404, "Connector not available")
    cls = get_plugin_connector_class(connector_type)
    if cls is None:
        raise HTTPException(404, "Connector not available")
    return cls


async def _owned_connection(manager, connector_type: str, connection_id: str, user_id: str):
    connection = await manager.get_connection(connection_id)
    if (
        connection is None
        or not connection.is_active
        or connection.connector_type != connector_type
        or connection.user_id != user_id
    ):
        raise HTTPException(404, "Connection not found")
    return connection


async def _existing_connection(
    manager, connector_type: str, user_id: str, connection_id: str | None
):
    if connection_id is not None:
        if not isinstance(connection_id, str) or len(connection_id) > 128:
            raise HTTPException(422, "Invalid connection ID")
        return await _owned_connection(manager, connector_type, connection_id, user_id)
    connections = await manager.list_connections(user_id=user_id, connector_type=connector_type)
    active = [connection for connection in connections if connection.is_active]
    if len(active) > 1:
        raise HTTPException(409, "Specify a connection ID")
    return active[0] if active else None


def _validated_config(cls, values: Any, existing=None) -> dict[str, str]:
    fields = plugin_config_fields(cls)
    names = {field["name"] for field in fields}
    secret_names = {field["name"] for field in fields if field["type"] == "secret"}
    if not isinstance(values, dict) or not all(isinstance(key, str) for key in values):
        raise HTTPException(422, "Invalid connector configuration")
    if values.keys() - names:
        raise HTTPException(422, "Unknown connector configuration field")
    pair = getattr(cls, "CREDENTIAL_PAIR", None)
    if pair is not None and sum(bool(values.get(key)) for key in pair) == 1:
        raise HTTPException(422, "Both credential fields must be supplied together")
    result = {
        key: value for key, value in (existing.config.items() if existing else ()) if key in names
    }
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 8192:
            raise HTTPException(422, "Invalid connector configuration field")
        if value or key not in result or key not in secret_names:
            result[key] = value
    for field in fields:
        if field["required"] and not result.get(field["name"], "").strip():
            raise HTTPException(422, f"Missing required field: {field['name']}")
    return result


def _require_encryption(cls, config: dict[str, str], user_id: str) -> None:
    secret_keys = {
        field["name"] for field in plugin_config_fields(cls) if field["type"] == "secret"
    }
    secret_keys.update(cls.SECRET_CONFIG_KEYS)
    if not any(config.get(key) for key in secret_keys):
        return
    if not get_master_secret():
        raise HTTPException(503, "OPENRAG_ENCRYPTION_KEY is required to store plugin credentials")
    for key in secret_keys:
        if config.get(key):
            envelope = encrypt_secret(config[key], tenant_id=user_id)
            if not isinstance(envelope, dict) or envelope.get("algorithm") != "AES-256-GCM":
                raise HTTPException(503, "Plugin secret encryption failed")


async def plugin_defaults(
    connector_type: str,
    connection_id: str | None = Query(default=None, max_length=128),
    connector_service=Depends(get_connector_service),
    user: User = Depends(require_permission("connectors:use")),
):
    cls = _plugin(connector_type)
    manager = connector_service.connection_manager
    connection = await _existing_connection(manager, connector_type, user.user_id, connection_id)
    fields = plugin_config_fields(cls)
    config = connection.config if connection else {}
    return {
        "connector_type": connector_type,
        "description": cls.CONNECTOR_DESCRIPTION,
        "kind": cls.CONNECTOR_KIND,
        "browse_capability": cls.BROWSE_CAPABILITY,
        "config_fields": fields,
        "connection_id": connection.connection_id if connection else None,
        "config": {
            field["name"]: config[field["name"]]
            for field in fields
            if field["type"] != "secret" and isinstance(config.get(field["name"]), str)
        },
        "secrets_set": {
            field["name"]: bool(config.get(field["name"]))
            for field in fields
            if field["type"] == "secret"
        },
    }


async def plugin_test(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(require_permission("connectors:create")),
):
    body = await _body(request)
    cls = _plugin(connector_type)
    manager = connector_service.connection_manager
    existing = await _existing_connection(manager, connector_type, user.user_id, body.connection_id)
    config = _validated_config(cls, body.config, existing)
    try:
        authenticated = await cls({**config, "user_id": user.user_id}).authenticate()
    except Exception:
        raise HTTPException(400, "Connector authentication failed") from None
    if not authenticated:
        raise HTTPException(400, "Connector authentication failed")
    return {"status": "ok"}


async def plugin_configure(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(require_permission("connectors:create")),
):
    body = await _body(request)
    cls = _plugin(connector_type)
    manager = connector_service.connection_manager
    existing = await _existing_connection(manager, connector_type, user.user_id, body.connection_id)
    config = _validated_config(cls, body.config, existing)
    _require_encryption(cls, config, user.user_id)
    if body.name is not None and (not isinstance(body.name, str) or len(body.name) > 120):
        raise HTTPException(422, "Invalid connection name")
    try:
        authenticated = await cls({**config, "user_id": user.user_id}).authenticate()
    except Exception:
        raise HTTPException(400, "Connector authentication failed") from None
    if not authenticated:
        raise HTTPException(400, "Connector authentication failed")

    if existing:
        previous_config, previous_name = existing.config, existing.name
        try:
            await manager.update_connection(
                existing.connection_id, config=config, name=body.name or existing.name
            )
        except Exception:
            existing.config, existing.name = previous_config, previous_name
            raise
        manager.active_connectors.pop(existing.connection_id, None)
        connection_id = existing.connection_id
    else:
        connection_id = str(uuid.uuid4())
        connection = ConnectionConfig(
            connection_id=connection_id,
            connector_type=connector_type,
            name=body.name or cls.CONNECTOR_NAME or connector_type,
            config=config,
            user_id=user.user_id,
        )
        manager.connections[connection_id] = connection
        try:
            await manager.save_connections()
        except Exception:
            if manager.connections.get(connection_id) is connection:
                manager.connections.pop(connection_id)
            raise
    return {"connection_id": connection_id, "status": "connected"}


async def plugin_picker_children(
    connector_type: str,
    connection_id: str,
    parent_id: str | None = Query(default=None, max_length=2048),
    cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=100, ge=1, le=200),
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("connectors:use")),
):
    cls = _plugin(connector_type)
    if cls.BROWSE_CAPABILITY not in ("hierarchical", "flat"):
        raise HTTPException(404, "Picker unavailable")
    manager = connector_service.connection_manager
    await _owned_connection(manager, connector_type, connection_id, user.user_id)
    try:
        connector = await manager.get_connector(connection_id)
    except Exception:
        raise HTTPException(502, "Connector authentication failed") from None
    if connector is None:
        raise HTTPException(401, "Connector authentication failed")
    if cls.BROWSE_CAPABILITY == "flat" and parent_id is not None:
        raise HTTPException(400, "Flat connector has no folders")
    try:
        if cls.BROWSE_CAPABILITY == "flat":
            listing = await connector.list_files(page_token=cursor, max_files=page_size)
        else:
            page = await connector.list_children(
                parent_id=parent_id, cursor=cursor, page_size=page_size
            )
    except ValueError:
        raise HTTPException(400, "Invalid browse scope or cursor") from None
    except Exception:
        raise HTTPException(502, "Connector browse failed") from None
    if cls.BROWSE_CAPABILITY == "flat":
        if (
            not isinstance(listing, dict)
            or not isinstance(listing.get("files"), list)
            or any(not isinstance(file, dict) for file in listing["files"])
        ):
            raise HTTPException(502, "Invalid connector browse response")
        page = {
            "nodes": [
                {
                    "id": file.get("id"),
                    "parent_id": None,
                    "kind": "file",
                    "name": file.get("name"),
                    **{key: file[key] for key in ("size", "modified_time") if key in file},
                }
                for file in listing["files"]
            ],
            "next_cursor": listing.get("next_page_token"),
        }
    if (
        not isinstance(page, dict)
        or not isinstance(page.get("nodes"), list)
        or len(page["nodes"]) > page_size
    ):
        raise HTTPException(502, "Invalid connector browse response")
    next_cursor = page.get("next_cursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 2048):
        raise HTTPException(502, "Invalid connector browse response")
    nodes: list[dict[str, Any]] = []
    for node in page["nodes"]:
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or not isinstance(node.get("name"), str)
            or node.get("kind") not in ("file", "folder")
            or (node.get("parent_id") is not None and not isinstance(node.get("parent_id"), str))
        ):
            raise HTTPException(502, "Invalid connector browse response")
        nodes.append(
            {
                "id": node["id"],
                "parent_id": node.get("parent_id"),
                "kind": node["kind"],
                "name": node["name"],
                **{key: node[key] for key in ("size", "modified_time") if key in node},
            }
        )
    from api.connectors import enrich_plugin_picker_nodes

    try:
        nodes = await enrich_plugin_picker_nodes(
            connector_type, nodes, session_manager, user.user_id, user.jwt_token
        )
    except Exception:
        raise HTTPException(503, "Picker status unavailable") from None
    return {"nodes": nodes, "next_cursor": next_cursor}
