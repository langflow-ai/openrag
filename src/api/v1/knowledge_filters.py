"""
Public API v1 Knowledge Filters endpoints.

Provides knowledge filter management.
Uses API key authentication — delegates to the main api/knowledge_filter.py handlers
but overrides the user dependency to use API keys.
"""
from fastapi import Depends
from api import knowledge_filter
from dependencies import (
    get_knowledge_filter_service,
    get_session_manager,
    get_api_key_user_async,
)
from session_manager import User


async def create_endpoint(
    body: knowledge_filter.CreateFilterBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """
    Create a new knowledge filter.

    POST /v1/knowledge-filters
    """
    return await knowledge_filter.create_knowledge_filter(
        body=body,
        knowledge_filter_service=knowledge_filter_service,
        session_manager=session_manager,
        user=user,
    )


async def search_endpoint(
    body: knowledge_filter.SearchFiltersBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """
    Search knowledge filters.

    POST /v1/knowledge-filters/search
    """
    return await knowledge_filter.search_knowledge_filters(
        body=body,
        knowledge_filter_service=knowledge_filter_service,
        session_manager=session_manager,
        user=user,
    )


async def get_endpoint(
    filter_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """
    Get a specific knowledge filter by ID.

    GET /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.get_knowledge_filter(
        filter_id=filter_id,
        knowledge_filter_service=knowledge_filter_service,
        session_manager=session_manager,
        user=user,
    )


async def update_endpoint(
    filter_id: str,
    body: knowledge_filter.UpdateFilterBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """
    Update a knowledge filter.

    PUT /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.update_knowledge_filter(
        filter_id=filter_id,
        body=body,
        knowledge_filter_service=knowledge_filter_service,
        session_manager=session_manager,
        user=user,
    )


async def delete_endpoint(
    filter_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_api_key_user_async),
):
    """
    Delete a knowledge filter.

    DELETE /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.delete_knowledge_filter(
        filter_id=filter_id,
        knowledge_filter_service=knowledge_filter_service,
        session_manager=session_manager,
        user=user,
    )
