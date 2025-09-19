from starlette.requests import Request
from starlette.responses import JSONResponse
import uuid
import json
from datetime import datetime
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def create_knowledge_filter(
    request: Request, knowledge_filter_service, session_manager
):
    """Create a new knowledge filter"""
    payload = await request.json()

    name = payload.get("name")
    if not name:
        return JSONResponse(
            {"error": "Knowledge filter name is required"}, status_code=400
        )

    description = payload.get("description", "")
    query_data = payload.get("queryData")
    if not query_data:
        return JSONResponse({"error": "Query data is required"}, status_code=400)

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    # Create knowledge filter document
    filter_id = str(uuid.uuid4())
    filter_doc = {
        "id": filter_id,
        "name": name,
        "description": description,
        "query_data": query_data,  # Store the full search query JSON
        "owner": user.user_id,
        "allowed_users": payload.get("allowedUsers", []),  # ACL field for future use
        "allowed_groups": payload.get("allowedGroups", []),  # ACL field for future use
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    result = await knowledge_filter_service.create_knowledge_filter(
        filter_doc, user_id=user.user_id, jwt_token=jwt_token
    )

    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=201)  # Created
    else:
        error_msg = result.get("error", "")
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def search_knowledge_filters(
    request: Request, knowledge_filter_service, session_manager
):
    """Search for knowledge filters by name, description, or query content"""
    payload = await request.json()

    query = payload.get("query", "")
    limit = payload.get("limit", 20)

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    result = await knowledge_filter_service.search_knowledge_filters(
        query, user_id=user.user_id, jwt_token=jwt_token, limit=limit
    )

    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def get_knowledge_filter(
    request: Request, knowledge_filter_service, session_manager
):
    """Get a specific knowledge filter by ID"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse(
            {"error": "Knowledge filter ID is required"}, status_code=400
        )

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )

    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def update_knowledge_filter(
    request: Request, knowledge_filter_service, session_manager
):
    """Update an existing knowledge filter by delete + recreate (due to DLS limitations)"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse(
            {"error": "Knowledge filter ID is required"}, status_code=400
        )

    payload = await request.json()

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    # First, get the existing knowledge filter
    existing_result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not existing_result.get("success"):
        return JSONResponse(
            {"error": "Knowledge filter not found or access denied"}, status_code=404
        )

    existing_filter = existing_result["filter"]

    # Delete the existing knowledge filter
    delete_result = await knowledge_filter_service.delete_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not delete_result.get("success"):
        return JSONResponse(
            {"error": "Failed to delete existing knowledge filter"}, status_code=500
        )

    # Create updated knowledge filter document with same ID
    updated_filter = {
        "id": filter_id,
        "name": payload.get("name", existing_filter["name"]),
        "description": payload.get("description", existing_filter["description"]),
        "query_data": payload.get("queryData", existing_filter["query_data"]),
        "owner": existing_filter["owner"],
        "allowed_users": payload.get(
            "allowedUsers", existing_filter.get("allowed_users", [])
        ),
        "allowed_groups": payload.get(
            "allowedGroups", existing_filter.get("allowed_groups", [])
        ),
        "created_at": existing_filter["created_at"],  # Preserve original creation time
        "updated_at": datetime.utcnow().isoformat(),
    }

    # Recreate the knowledge filter
    result = await knowledge_filter_service.create_knowledge_filter(
        updated_filter, user_id=user.user_id, jwt_token=jwt_token
    )

    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)  # Updated successfully
    else:
        error_msg = result.get("error", "")
        if (
            "AuthenticationException" in error_msg
            or "access denied" in error_msg.lower()
        ):
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def delete_knowledge_filter(
    request: Request, knowledge_filter_service, session_manager
):
    """Delete a knowledge filter"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse(
            {"error": "Knowledge filter ID is required"}, status_code=400
        )

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    result = await knowledge_filter_service.delete_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )

    # Return appropriate HTTP status codes
    if result.get("success"):
        return JSONResponse(result, status_code=200)
    else:
        error_msg = result.get("error", "")
        if "not found" in error_msg.lower() or "already deleted" in error_msg.lower():
            return JSONResponse(result, status_code=404)
        elif (
            "access denied" in error_msg.lower()
            or "insufficient permissions" in error_msg.lower()
        ):
            return JSONResponse(result, status_code=403)
        else:
            return JSONResponse(result, status_code=500)


async def subscribe_to_knowledge_filter(
    request: Request, knowledge_filter_service, monitor_service, session_manager
):
    """Create a subscription to a knowledge filter"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse(
            {"error": "Knowledge filter ID is required"}, status_code=400
        )

    payload = await request.json()
    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    # Get the knowledge filter to validate it exists and get its details
    filter_result = await knowledge_filter_service.get_knowledge_filter(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not filter_result.get("success"):
        return JSONResponse(
            {"error": "Knowledge filter not found or access denied"}, status_code=404
        )

    filter_doc = filter_result["filter"]

    # Create the monitor for this subscription
    monitor_result = await monitor_service.create_knowledge_filter_monitor(
        filter_id=filter_id,
        filter_name=filter_doc["name"],
        query_data=filter_doc["query_data"],
        user_id=user.user_id,
        jwt_token=jwt_token,
        notification_config=payload.get("notification_config"),
    )

    if not monitor_result.get("success"):
        return JSONResponse(monitor_result, status_code=500)

    # Store subscription info in the knowledge filter document
    subscription_data = {
        "subscription_id": monitor_result["subscription_id"],
        "monitor_id": monitor_result["monitor_id"],
        "webhook_url": monitor_result["webhook_url"],
        "created_at": datetime.utcnow().isoformat(),
        "notification_config": payload.get("notification_config", {}),
    }

    # Add subscription to the filter document
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
        # If we can't update the filter doc, clean up the monitor
        await monitor_service.delete_monitor(
            monitor_result["monitor_id"], user.user_id, jwt_token
        )
        return JSONResponse({"error": "Failed to create subscription"}, status_code=500)


async def list_knowledge_filter_subscriptions(
    request: Request, knowledge_filter_service, session_manager
):
    """List subscriptions for a knowledge filter"""
    filter_id = request.path_params.get("filter_id")
    if not filter_id:
        return JSONResponse(
            {"error": "Knowledge filter ID is required"}, status_code=400
        )

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

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
    request: Request, knowledge_filter_service, monitor_service, session_manager
):
    """Cancel a subscription to a knowledge filter"""
    filter_id = request.path_params.get("filter_id")
    subscription_id = request.path_params.get("subscription_id")

    if not filter_id or not subscription_id:
        return JSONResponse(
            {"error": "Knowledge filter ID and subscription ID are required"},
            status_code=400,
        )

    user = request.state.user
    jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

    # Get subscription details to find the monitor ID
    subscriptions_result = await knowledge_filter_service.get_filter_subscriptions(
        filter_id, user_id=user.user_id, jwt_token=jwt_token
    )
    if not subscriptions_result.get("success"):
        return JSONResponse(
            {"error": "Knowledge filter not found or access denied"}, status_code=404
        )

    # Find the specific subscription
    subscription = None
    for sub in subscriptions_result.get("subscriptions", []):
        if sub.get("subscription_id") == subscription_id:
            subscription = sub
            break

    if not subscription:
        return JSONResponse({"error": "Subscription not found"}, status_code=404)

    # Delete the monitor
    monitor_result = await monitor_service.delete_monitor(
        subscription["monitor_id"], user.user_id, jwt_token
    )

    # Remove subscription from the filter document
    remove_result = await knowledge_filter_service.remove_subscription(
        filter_id, subscription_id, user_id=user.user_id, jwt_token=jwt_token
    )

    if remove_result.get("success"):
        return JSONResponse(
            {"success": True, "message": "Subscription cancelled successfully"},
            status_code=200,
        )
    else:
        return JSONResponse({"error": "Failed to cancel subscription"}, status_code=500)


async def knowledge_filter_webhook(
    request: Request, knowledge_filter_service, session_manager
):
    """Handle webhook notifications from OpenSearch monitors"""
    filter_id = request.path_params.get("filter_id")
    subscription_id = request.path_params.get("subscription_id")

    if not filter_id or not subscription_id:
        return JSONResponse({"error": "Invalid webhook URL"}, status_code=400)

    try:
        # Get the webhook payload
        payload = await request.json()

        logger.info(
            "Knowledge filter webhook received",
            filter_id=filter_id,
            subscription_id=subscription_id,
            payload_size=len(str(payload)),
        )

        # Extract findings from the payload
        findings = payload.get("findings", [])
        if not findings:
            logger.info(
                "No findings in webhook payload", subscription_id=subscription_id
            )
            return JSONResponse({"status": "no_findings"})

        # Process the findings - these are the documents that matched the knowledge filter
        matched_documents = []
        for finding in findings:
            # Extract document information from the finding
            matched_documents.append(
                {
                    "document_id": finding.get("_id"),
                    "index": finding.get("_index"),
                    "source": finding.get("_source", {}),
                    "score": finding.get("_score"),
                }
            )

        # Log the matched documents
        logger.info(
            "Knowledge filter matched documents",
            filter_id=filter_id,
            matched_count=len(matched_documents),
        )
        for doc in matched_documents:
            logger.debug(
                "Matched document",
                document_id=doc["document_id"],
                index=doc["index"],
                score=doc.get("score"),
            )

        # Here you could add additional processing:
        # - Send notifications to external webhooks
        # - Email notifications
        # - Store alerts in a database
        # - Trigger other workflows

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
        return JSONResponse(
            {"error": f"Webhook processing failed: {str(e)}"}, status_code=500
        )
