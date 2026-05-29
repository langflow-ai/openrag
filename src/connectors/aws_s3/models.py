"""Pydantic request/response models for AWS S3 API endpoints."""

from pydantic import BaseModel


class S3ConfigureBody(BaseModel):
    access_key: str | None = None
    secret_key: str | None = None
    endpoint_url: str | None = None
    region: str | None = None
    session_token: str | None = None
    bucket_names: list[str] | None = None
    connection_id: str | None = None
