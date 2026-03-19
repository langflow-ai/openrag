"""Pydantic request/response models for AWS S3 API endpoints."""

from typing import List, Optional
from pydantic import BaseModel


class S3ConfigureBody(BaseModel):
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_names: Optional[List[str]] = None
    connection_id: Optional[str] = None
