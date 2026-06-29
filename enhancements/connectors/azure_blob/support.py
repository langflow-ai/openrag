"""Support helpers for Azure Blob API endpoints.

Pure (non-async) business logic for credential resolution and config dict
construction, keeping the route handlers thin.
"""

import os

from .models import AzureBlobConfigureBody


def build_azure_blob_config(
    body: AzureBlobConfigureBody,
    existing_config: dict,
) -> tuple[dict, str | None]:
    """Resolve Azure Blob credentials and build the connection config dict.

    Resolution order for each credential: request body → environment variable
    → existing connection config.

    Returns:
        (conn_config, None)  on success
        ({}, error_message)  on validation failure
    """
    conn_config: dict = {"auth_mode": body.auth_mode}

    if body.auth_mode == "connection_string":
        connection_string = (
            body.connection_string
            or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            or existing_config.get("connection_string")
        )
        if not connection_string:
            return {}, "Connection string mode requires a connection_string"
        conn_config["connection_string"] = connection_string
    elif body.auth_mode == "account_key":
        account_name = (
            body.account_name
            or os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
            or existing_config.get("account_name")
        )
        account_key = (
            body.account_key
            or os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
            or existing_config.get("account_key")
        )
        if not account_name or not account_key:
            return {}, "Account key mode requires account_name and account_key"
        conn_config["account_name"] = account_name
        conn_config["account_key"] = account_key
        endpoint = (
            body.endpoint
            or os.getenv("AZURE_STORAGE_ENDPOINT")
            or existing_config.get("endpoint_url")
        )
        if endpoint:
            conn_config["endpoint_url"] = endpoint
    else:
        return {}, f"Unknown auth_mode: {body.auth_mode!r}"

    if body.container_names is not None:
        conn_config["container_names"] = body.container_names
    elif existing_config.get("container_names"):
        conn_config["container_names"] = existing_config["container_names"]

    return conn_config, None
