"""Pydantic request/response models for IBM COS API endpoints."""

from typing import List, Optional
from pydantic import BaseModel


class IBMCOSConfigureBody(BaseModel):
    auth_mode: str  # "iam" or "hmac"
    endpoint: str
    # IAM fields
    api_key: Optional[str] = None
    service_instance_id: Optional[str] = None
    auth_endpoint: Optional[str] = None
    # HMAC fields
    hmac_access_key: Optional[str] = None
    hmac_secret_key: Optional[str] = None
    # Optional bucket selection
    bucket_names: Optional[List[str]] = None
    # Optional: update an existing connection
    connection_id: Optional[str] = None
