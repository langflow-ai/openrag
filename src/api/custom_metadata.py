"""Custom metadata discovery endpoints scoped by document visibility."""

import re

from fastapi import Depends, Query
from fastapi.responses import JSONResponse

from config.settings import get_index_name
from dependencies import (
    get_session_manager,
    require_api_key_permission,
    require_permission,
)
from services.custom_metadata_service import CustomMetadataService
from session_manager import User


async def _fields(user: User, session_manager) -> JSONResponse:
    client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    result = await client.search(
        index=get_index_name(),
        body={
            "size": 0,
            "aggs": {
                "metadata": {
                    "nested": {"path": "metadata_entries"},
                    "aggs": {"keys": {"terms": {"field": "metadata_entries.key", "size": 200}}},
                }
            },
        },
    )
    field_types = await CustomMetadataService().get_field_types()
    buckets = result.get("aggregations", {}).get("metadata", {}).get("keys", {}).get("buckets", [])
    return JSONResponse(
        {
            "fields": [
                {
                    "key": bucket["key"],
                    "type": field_types.get(bucket["key"]),
                    "document_count": bucket.get("doc_count", 0),
                }
                for bucket in buckets
                if bucket.get("key") in field_types
            ]
        }
    )


async def _values(key: str, query: str, limit: int, user: User, session_manager) -> JSONResponse:
    key = key.strip().lower()
    field_types = await CustomMetadataService().get_field_types()
    metadata_type = field_types.get(key)
    if metadata_type is None:
        return JSONResponse({"error": f"Unknown custom metadata key '{key}'"}, status_code=404)
    value_field = CustomMetadataService.VALUE_FIELDS[metadata_type]
    include = f".*{re.escape(query)}.*" if query else None
    terms: dict = {"field": f"metadata_entries.{value_field}", "size": min(limit, 100)}
    if include and metadata_type == "string":
        terms["include"] = include
    client = session_manager.get_user_opensearch_client(user.user_id, user.jwt_token)
    result = await client.search(
        index=get_index_name(),
        body={
            "size": 0,
            "aggs": {
                "metadata": {
                    "nested": {"path": "metadata_entries"},
                    "aggs": {
                        "selected_key": {
                            "filter": {"term": {"metadata_entries.key": key}},
                            "aggs": {"values": {"terms": terms}},
                        }
                    },
                }
            },
        },
    )
    buckets = (
        result.get("aggregations", {})
        .get("metadata", {})
        .get("selected_key", {})
        .get("values", {})
        .get("buckets", [])
    )
    return JSONResponse(
        {
            "key": key,
            "type": metadata_type,
            "values": [
                {"value": bucket.get("key"), "document_count": bucket.get("doc_count", 0)}
                for bucket in buckets
            ],
        }
    )


async def list_fields(
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("search:use")),
):
    return await _fields(user, session_manager)


async def list_values(
    key: str,
    query: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_permission("search:use")),
):
    return await _values(key, query, limit, user, session_manager)


async def list_fields_v1(
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_api_key_permission("search:use")),
):
    return await _fields(user, session_manager)


async def list_values_v1(
    key: str,
    query: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    session_manager=Depends(get_session_manager),
    user: User = Depends(require_api_key_permission("search:use")),
):
    return await _values(key, query, limit, user, session_manager)
