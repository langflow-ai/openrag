from typing import Optional, Any, List

from fastapi import Depends, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
import uuid
import json
from datetime import datetime
from utils.logging_config import get_logger
from dependencies import get_knowledge_filter_service, get_monitor_service, get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


def normalize_query_data(query_data: str | dict) -> str:
    """
    Normalize query_data to ensure all required fields exist with defaults.
    This prevents frontend crashes when API-created filters have incomplete data.
    """
    if isinstance(query_data, str):
        try:
            data = json.loads(query_data)
        except json.JSONDecodeError:
            data = {}
    else:
        data = query_data or {}

    filters = data.get("filters") or {}
    normalized_filters = {
        "data_sources": filters.get("data_sources", ["*"]),
        "document_types": filters.get("document_types", ["*"]),
        "owners": filters.get("owners", ["*"]),
        "connector_types": filters.get("connector_types", ["*"]),
    }

    normalized = {
        "query": data.get("query", ""),
        "filters": normalized_filters,
        "limit": data.get("limit", 10),
        "scoreThreshold": data.get("scoreThreshold", 0),
        "color": data.get("color", "zinc"),
        "icon": data.get("icon", "filter"),
    }

    return json.dumps(normalized)


class CreateFilterBody(BaseModel):
    name: str
    description: str = ""
    queryData: Optional[Any] = None
    allowedUsers: List[str] = []
    allowedGroups: List[str] = []


class SearchFiltersBody(BaseModel):
    query: str = ""
    limit: int = 20


class UpdateFilterBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    queryData: Optional[Any] = None
    allowedUsers: Optional[List[str]] = None
    allowedGroups: Optional[List[str]] = None


class SubscribeBody(BaseModel):
    notification_config: Optional[dict] = None


async def create_knowledge_filter(
    body: CreateFilterBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Create a new knowledge filter"""
    if not body.name:
        return JSONResponse({"error": "Knowledge filter name is required"}, status_code=400)

    if not body.queryData:
        return JSONResponse({"error": "Query data is required"}, status_code=400)

    try:
        normalized_query_data = normalize_query_data(body.queryData)
    except Exception as e:
        logger.error(f"Failed to normalize query_data: {e}")
        return JSONResponse({"error": f"Invalid queryData format: {str(e)}"}, status_code=400)

    jwt_token = user.jwt_token

    filter_id = str(uuid.uuid4())
    filter_doc = {
        "id": filter_id,
        "name": body.name,
        "description": body.description,
        "query_data": normalized_query_data,
        "owner": user.user_id,
        "allowed_users": body.allowedUsers,
        "allowed_groups": body.allowedGroups,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    result = await knowledge_filter_service.create_knowledge_filter(
        filter_doc, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return JSONResponse(result, status_code=201)
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def search_knowledge_filters(
    body: SearchFiltersBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Search for knowledge filters by name, description, or query content"""
    jwt_token = user.jwt_token
    result = await knowledge_filter_service.search_knowledge_filters(
        body.query, user_id=user.user_id, jwt_token=jwt_token, limit=body.limit
    )

    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def get_knowledge_filter(
    filter_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Get a specific knowledge filter by ID"""
    jwt_token = user.jwt_token
    result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def update_knowledge_filter(
    filter_id: str,
    body: UpdateFilterBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Update an existing knowledge filter by delete + recreate"""
    jwt_token = user.jwt_token

    existing_result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not existing_result.get("success"):
        return JSONResponse({"error": "Knowledge filter not found or access denied"}, status_code=404)

    existing_filter = existing_result["filter"]

    delete_result = await knowledge_filter_service.delete_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not delete_result.get("success"):
        return JSONResponse({"error": "Failed to delete existing knowledge filter"}, status_code=500)

    query_data = body.queryData if body.queryData is not None else existing_filter["query_data"]
    try:
        normalized_query_data = normalize_query_data(query_data)
    except Exception as e:
        logger.error(f"Failed to normalize query_data: {e}")
        return JSONResponse({"error": f"Invalid queryData format: {str(e)}"}, status_code=400)

    updated_filter = {
        "id": filter_id,
        "name": body.name if body.name is not None else existing_filter["name"],
        "description": body.description if body.description is not None else existing_filter["description"],
        "query_data": normalized_query_data,
        "owner": existing_filter["owner"],
        "allowed_users": body.allowedUsers if body.allowedUsers is not None else existing_filter.get("allowed_users", []),
        "allowed_groups": body.allowedGroups if body.allowedGroups is not None else existing_filter.get("allowed_groups", []),
        "created_at": existing_filter["created_at"],
        "updated_at": datetime.utcnow().isoformat(),
    }

    result = await knowledge_filter_service.create_knowledge_filter(
        updated_filter, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def delete_knowledge_filter(
    filter_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Delete a knowledge filter"""
    jwt_token = user.jwt_token
    result = await knowledge_filter_service.delete_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower() or "already deleted" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif "access denied" in error_msg.lower() or "insufficient permissions" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def subscribe_to_knowledge_filter(
    filter_id: str,
    body: SubscribeBody,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    monitor_service=Depends(get_monitor_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Create a subscription to a knowledge filter"""
    jwt_token = user.jwt_token

    filter_result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not filter_result.get("success"):
        return JSONResponse({"error": "Knowledge filter not found or access denied"}, status_code=404)

    filter_doc = filter_result["filter"]

    monitor_result = await monitor_service.create_knowledge_filter_monitor(
        filter_id=filter_id,
        filter_name=filter_doc["name"],
        query_data=filter_doc["query_data"],
        user_id=user.user_id,
        jwt_token=jwt_token,
        notification_config=body.notification_config,
    )

    if not monitor_result.get("success"):
        return JSONResponse(monitor_result, status_code=500)

    subscription_data = {
        "subscription_id": monitor_result["subscription_id"],
        "monitor_id": monitor_result["monitor_id"],
        "webhook_url": monitor_result["webhook_url"],
        "created_at": datetime.utcnow().isoformat(),
        "notification_config": body.notification_config or {},
    }

    update_result = await knowledge_filter_service.add_subscription(
        filter_id, subscription_data, user_id=user.user_id, jwt_token=jwt_token
    )

    if update_result.get("success"):
        return JSONResponse(
            {
                "success": True,
                "subscription_id": monitor_result["subscription_id"],
                "monitor_id": monitor_result["monitor_id"],
                "webhook_url": monitor_result["webhook_url"],
                "message": f"Successfully subscribed to knowledge filter: {filter_doc['name']}",
            },
            status_code=201,
        )
    else:
        await monitor_service.delete_monitor(monitor_result["monitor_id"], user.user_id, jwt_token)
        return JSONResponse({"error": "Failed to create subscription"}, status_code=500)


async def list_knowledge_filter_subscriptions(
    filter_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """List subscriptions for a knowledge filter"""
    jwt_token = user.jwt_token
    result = await knowledge_filter_service.get_filter_subscriptions(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )

    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif "access denied" in error_msg.lower():
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def cancel_knowledge_filter_subscription(
    filter_id: str,
    subscription_id: str,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    monitor_service=Depends(get_monitor_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Cancel a subscription to a knowledge filter"""
    jwt_token = user.jwt_token

    subscriptions_result = await knowledge_filter_service.get_filter_subscriptions(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not subscriptions_result.get("success"):
        return JSONResponse({"error": "Knowledge filter not found or access denied"}, status_code=404)

    subscription = None
    for sub in subscriptions_result.get("subscriptions", []):
        if sub.get("subscription_id") == subscription_id:
            subscription = sub
            break

    if not subscription:
        return JSONResponse({"error": "Subscription not found"}, status_code=404)

    await monitor_service.delete_monitor(subscription["monitor_id"], user.user_id, jwt_token)

    remove_result = await knowledge_filter_service.remove_subscription(
        filter_id, subscription_id, user_id=user.user_id, jwt_token=jwt_token
    )

    if remove_result.get("success"):
        return JSONResponse({"success": True, "message": "Subscription cancelled successfully"}, status_code=200)
    else:
        return JSONResponse({"error": "Failed to cancel subscription"}, status_code=500)


async def knowledge_filter_webhook(
    filter_id: str,
    subscription_id: str,
    request: Request,
    knowledge_filter_service=Depends(get_knowledge_filter_service),
    session_manager=Depends(get_session_manager),
):
    """Handle webhook notifications from OpenSearch monitors"""
    try:
        payload = await request.json()

        logger.info(
            "Knowledge filter webhook received",
            filter_id=filter_id,
            subscription_id=subscription_id,
            payload_size=len(str(payload)),
        )

        findings = payload.get("findings", [])
        if not findings:
            logger.info("No findings in webhook payload", subscription_id=subscription_id)
            return JSONResponse({"status": "no_findings"})

        matched_documents = []
        for finding in findings:
            matched_documents.append(
                {
                    "document_id": finding.get("_id"),
                    "index": finding.get("_index"),
                    "source": finding.get("_source", {}),
                    "score": finding.get("_score"),
                }
            )

        logger.info(
            "Knowledge filter matched documents",
            filter_id=filter_id,
            matched_count=len(matched_documents),
        )

        return JSONResponse(
            {
                "status": "processed",
                "filter_id": filter_id,
                "subscription_id": subscription_id,
                "matched_documents": len(matched_documents),
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(
            "Failed to process knowledge filter webhook",
            filter_id=filter_id,
            subscription_id=subscription_id,
            error=str(e),
        )
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": f"Webhook processing failed: {str(e)}"}, status_code=500)
