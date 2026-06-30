"""Pydantic request/response models for IBM COS API endpoints."""

from pydantic import BaseModel


class IBMCOSConfigureBody(BaseModel):
    auth_mode: str  # "iam" or "hmac"
    endpoint: str
    # IAM fields
    api_key: str | None = None
    service_instance_id: str | None = None
    auth_endpoint: str | None = None
    # HMAC fields
    hmac_access_key: str | None = None
    hmac_secret_key: str | None = None
    # Optional bucket selection
    bucket_names: list[str] | None = None
    # Optional: update an existing connection
    connection_id: str | None = None
