from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def list_connectors(request: Request, connector_service, session_manager):
    """List available connector types with metadata"""
    try:
        connector_types = (
            connector_service.connection_manager.get_available_connector_types()
        )
        return JSONResponse({"connectors": connector_types})
    except Exception as e:
        logger.error("Error listing connectors", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def connector_sync(request: Request, connector_service, session_manager):
    """Sync files from all active connections of a connector type"""
    connector_type = request.path_params.get("connector_type", "google_drive")
    data = await request.json()
    max_files = data.get("max_files")

    if not data.get("selected_files"):
        return JSONResponse({"error": "selected_files is required"}, status_code=400)

    try:
        logger.debug("Starting connector sync", connector_type=connector_type, max_files=max_files)

        user = request.state.user
        jwt_token = request.state.jwt_token
        logger.debug("User authenticated", user_id=user.user_id)

        # Get all active connections for this connector type and user
        connections = await connector_service.connection_manager.list_connections(
            user_id=user.user_id, connector_type=connector_type
        )

        active_connections = [conn for conn in connections if conn.is_active]
        if not active_connections:
            return JSONResponse(
                {"error": f"No active {connector_type} connections found"},
                status_code=404,
            )

        # Start sync tasks for all active connections
        task_ids = []
        for connection in active_connections:
            logger.debug("About to call sync_connector_files for connection", connection_id=connection.connection_id)
            task_id = await connector_service.sync_connector_files(
                connection.connection_id,
                user.user_id,
                max_files,
                jwt_token=jwt_token,
                # NEW: thread picker selections through
                selected_files=data.get("selected_files"),
                selected_folders=data.get("selected_folders"),
            )
            task_ids.append(task_id)
            logger.debug("Got task ID", task_id=task_id)

        return JSONResponse(
            {
                "task_ids": task_ids,
                "status": "sync_started",
                "message": f"Started syncing files from {len(active_connections)} {connector_type} connection(s)",
                "connections_synced": len(active_connections),
            },
            status_code=201,
        )

    except Exception as e:
        import sys
        import traceback

        error_msg = f"[ERROR] Connector sync failed: {str(e)}"
        logger.error(error_msg)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()

        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


async def connector_status(request: Request, connector_service, session_manager):
    """Get connector status for authenticated user"""
    connector_type = request.path_params.get("connector_type", "google_drive")
    user = request.state.user

    # Get connections for this connector type and user
    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type=connector_type
    )

    # Check if there are any active connections
    active_connections = [conn for conn in connections if conn.is_active]
    has_authenticated_connection = len(active_connections) > 0

    return JSONResponse(
        {
            "connector_type": connector_type,
            "authenticated": has_authenticated_connection,
            "status": "connected" if has_authenticated_connection else "not_connected",
            "connections": [
                {
                    "connection_id": conn.connection_id,
                    "name": conn.name,
                    "is_active": conn.is_active,
                    "created_at": conn.created_at.isoformat(),
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                }
                for conn in connections
            ],
        }
    )


async def connector_webhook(request: Request, connector_service, session_manager):
    """Handle webhook notifications from any connector type"""
    connector_type = request.path_params.get("connector_type")
    if connector_type is None:
        connector_type = "unknown"

    # Handle webhook validation (connector-specific)
    temp_config = {"token_file": "temp.json"}
    from connectors.connection_manager import ConnectionConfig

    temp_connection = ConnectionConfig(
        connection_id="temp",
        connector_type=str(connector_type),
        name="temp",
        config=temp_config,
    )
    try:
        temp_connector = connector_service.connection_manager._create_connector(
            temp_connection
        )
        validation_response = temp_connector.handle_webhook_validation(
            request.method, dict(request.headers), dict(request.query_params)
        )
        if validation_response:
            return PlainTextResponse(validation_response)
    except (NotImplementedError, ValueError):
        # Connector type not found or validation not needed
        pass

    try:
        # Get the raw payload and headers
        payload = {}
        headers = dict(request.headers)

        if request.method == "POST":
            content_type = headers.get("content-type", "").lower()
            if "application/json" in content_type:
                payload = await request.json()
            else:
                # Some webhooks send form data or plain text
                body = await request.body()
                payload = {"raw_body": body.decode("utf-8") if body else ""}
        else:
            # GET webhooks use query params
            payload = dict(request.query_params)

        # Add headers to payload for connector processing
        payload["_headers"] = headers
        payload["_method"] = request.method

        logger.info("Webhook notification received", connector_type=connector_type)

        # Extract channel/subscription ID using connector-specific method
        try:
            temp_connector = connector_service.connection_manager._create_connector(
                temp_connection
            )
            channel_id = temp_connector.extract_webhook_channel_id(payload, headers)
        except (NotImplementedError, ValueError):
            channel_id = None

        if not channel_id:
            logger.warning("No channel ID found in webhook", connector_type=connector_type)
            return JSONResponse({"status": "ignored", "reason": "no_channel_id"})

        # Find the specific connection for this webhook
        connection = (
            await connector_service.connection_manager.get_connection_by_webhook_id(
                channel_id
            )
        )
        if not connection or not connection.is_active:
            logger.info("Unknown webhook channel, will auto-expire", channel_id=channel_id)
            return JSONResponse(
                {"status": "ignored_unknown_channel", "channel_id": channel_id}
            )

        # Process webhook for the specific connection
        try:
            # Get the connector instance
            connector = await connector_service._get_connector(connection.connection_id)
            if not connector:
                logger.error("Could not get connector for connection", connection_id=connection.connection_id)
                return JSONResponse(
                    {"status": "error", "reason": "connector_not_found"}
                )

            # Let the connector handle the webhook and return affected file IDs
            affected_files = await connector.handle_webhook(payload)

            if affected_files:
                logger.info("Webhook connection files affected", connection_id=connection.connection_id, affected_count=len(affected_files))

                # Generate JWT token for the user (needed for OpenSearch authentication)
                user = session_manager.get_user(connection.user_id)
                if user:
                    jwt_token = session_manager.create_jwt_token(user)
                else:
                    jwt_token = None

                # Trigger incremental sync for affected files
                task_id = await connector_service.sync_specific_files(
                    connection.connection_id,
                    connection.user_id,
                    affected_files,
                    jwt_token=jwt_token,
                )

                result = {
                    "connection_id": connection.connection_id,
                    "task_id": task_id,
                    "affected_files": len(affected_files),
                }
            else:
                # No specific files identified - just log the webhook
                logger.info("Webhook general change detected, no specific files", connection_id=connection.connection_id)

                result = {
                    "connection_id": connection.connection_id,
                    "action": "logged_only",
                    "reason": "no_specific_files",
                }

            return JSONResponse(
                {
                    "status": "processed",
                    "connector_type": connector_type,
                    "channel_id": channel_id,
                    **result,
                }
            )

        except Exception as e:
            logger.error("Failed to process webhook for connection", connection_id=connection.connection_id, error=str(e))
            import traceback

            traceback.print_exc()
            return JSONResponse(
                {
                    "status": "error",
                    "connector_type": connector_type,
                    "channel_id": channel_id,
                    "error": str(e),
                },
                status_code=500,
            )

    except Exception as e:
        import traceback

        logger.error("Webhook processing failed", error=str(e))
        traceback.print_exc()
        return JSONResponse(
            {"error": f"Webhook processing failed: {str(e)}"}, status_code=500
        )

async def connector_token(request: Request, connector_service, session_manager):
    """Get access token for connector API calls (e.g., Google Picker)"""
    connector_type = request.path_params.get("connector_type")
    connection_id = request.query_params.get("connection_id")

    if not connection_id:
        return JSONResponse({"error": "connection_id is required"}, status_code=400)

    user = request.state.user

    try:
        # Get the connection and verify it belongs to the user
        connection = await connector_service.connection_manager.get_connection(connection_id)
        if not connection or connection.user_id != user.user_id:
            return JSONResponse({"error": "Connection not found"}, status_code=404)

        # Get the connector instance
        connector = await connector_service._get_connector(connection_id)
        if not connector:
            return JSONResponse({"error": "Connector not available"}, status_code=404)

        # For Google Drive, get the access token
        if connector_type == "google_drive" and hasattr(connector, 'oauth'):
            await connector.oauth.load_credentials()
            if connector.oauth.creds and connector.oauth.creds.valid:
                return JSONResponse({
                    "access_token": connector.oauth.creds.token,
                    "expires_in": (connector.oauth.creds.expiry.timestamp() - 
                                 __import__('time').time()) if connector.oauth.creds.expiry else None
                })
            else:
                return JSONResponse({"error": "Invalid or expired credentials"}, status_code=401)

        return JSONResponse({"error": "Token not available for this connector type"}, status_code=400)

    except Exception as e:
        print(f"Error getting connector token: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
