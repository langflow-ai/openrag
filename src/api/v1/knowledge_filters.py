"""
Public API v1 Knowledge Filters endpoints.

Provides knowledge filter management.
Uses API key authentication.
"""
from starlette.requests import Request
from api import knowledge_filter


async def create_endpoint(request: Request, knowledge_filter_service, session_manager):
    """
    Create a new knowledge filter.

    POST /v1/knowledge-filters
    """
    return await knowledge_filter.create_knowledge_filter(
        request, knowledge_filter_service, session_manager
    )


async def search_endpoint(request: Request, knowledge_filter_service, session_manager):
    """
    Search knowledge filters.

    POST /v1/knowledge-filters/search
    """
    return await knowledge_filter.search_knowledge_filters(
        request, knowledge_filter_service, session_manager
    )


async def get_endpoint(request: Request, knowledge_filter_service, session_manager):
    """
    Get a specific knowledge filter by ID.

    GET /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.get_knowledge_filter(
        request, knowledge_filter_service, session_manager
    )


async def update_endpoint(request: Request, knowledge_filter_service, session_manager):
    """
    Update a knowledge filter.

    PUT /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.update_knowledge_filter(
        request, knowledge_filter_service, session_manager
    )


async def delete_endpoint(request: Request, knowledge_filter_service, session_manager):
    """
    Delete a knowledge filter.

    DELETE /v1/knowledge-filters/{filter_id}
    """
    return await knowledge_filter.delete_knowledge_filter(
        request, knowledge_filter_service, session_manager
    )
