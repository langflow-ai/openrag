"""Pydantic request/response models for Azure Blob API endpoints."""

from pydantic import BaseModel


class AzureBlobConfigureBody(BaseModel):
    auth_mode: str  # "connection_string" or "account_key"
    # connection_string mode
    connection_string: str | None = None
    # account_key mode
    account_name: str | None = None
    account_key: str | None = None
    endpoint: str | None = None  # optional custom blob endpoint (Azurite / sovereign)
    # Optional container selection
    container_names: list[str] | None = None
    # Optional: update an existing connection
    connection_id: str | None = None
