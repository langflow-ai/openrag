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
        logger.info("Error listing connectors", error=str(e))
        return JSONResponse({"connectors": []})


async def connector_sync(request: Request, connector_service, session_manager):
    """Sync files from all active connections of a connector type"""
    connector_type = request.path_params.get("connector_type", "google_drive")
    data = await request.json()
    max_files = data.get("max_files")
    selected_files = data.get("selected_files")

    try:
        logger.debug(
            "Starting connector sync",
            connector_type=connector_type,
            max_files=max_files,
        )
        user = request.state.user
        jwt_token = session_manager.get_effective_jwt_token(user.user_id, request.state.jwt_token)

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

        # Find the first connection that actually works
        working_connection = None
        for connection in active_connections:
            logger.debug(
                "Testing connection authentication",
                connection_id=connection.connection_id,
            )
            try:
                # Get the connector instance and test authentication
                connector = await connector_service.get_connector(connection.connection_id)
                if connector and await connector.authenticate():
                    working_connection = connection
                    logger.debug(
                        "Found working connection",
                        connection_id=connection.connection_id,
                    )
                    break
                else:
                    logger.debug(
                        "Connection authentication failed",
                        connection_id=connection.connection_id,
                    )
            except Exception as e:
                logger.debug(
                    "Connection validation failed",
                    connection_id=connection.connection_id,
                    error=str(e),
                )
                continue

        if not working_connection:
            return JSONResponse(
                {"error": f"No working {connector_type} connections found"},
                status_code=404,
            )

        # Use the working connection
        logger.debug(
            "Starting sync with working connection",
            connection_id=working_connection.connection_id,
        )
        
        if selected_files:
            task_id = await connector_service.sync_specific_files(
                working_connection.connection_id,
                user.user_id,
                selected_files,
                jwt_token=jwt_token,
            )
        else:
            task_id = await connector_service.sync_connector_files(
                working_connection.connection_id,
                user.user_id,
                max_files,
                jwt_token=jwt_token,
            )
        task_ids = [task_id]
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
        logger.error("Connector sync failed", error=str(e))
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


async def connector_status(request: Request, connector_service, session_manager):
    """Get connector status for authenticated user"""
    connector_type = request.path_params.get("connector_type", "google_drive")
    user = request.state.user

    # Get connections for this connector type and user
    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type=connector_type
    )

    # Get the connector for each connection
    connection_client_ids = {}
    for connection in connections:
        try:
            connector = await connector_service._get_connector(connection.connection_id)
            if connector is not None:
                connection_client_ids[connection.connection_id] = connector.get_client_id()
            else:
                connection_client_ids[connection.connection_id] = None
        except Exception as e:
            logger.warning(
                "Could not get connector for connection",
                connection_id=connection.connection_id,
                error=str(e),
            )
            connection.connector = None

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
                    "client_id": connection_client_ids.get(conn.connection_id),
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
            logger.warning(
                "No channel ID found in webhook", connector_type=connector_type
            )
            return JSONResponse({"status": "ignored", "reason": "no_channel_id"})

        # Find the specific connection for this webhook
        connection = (
            await connector_service.connection_manager.get_connection_by_webhook_id(
                channel_id
            )
        )
        if not connection or not connection.is_active:
            logger.info(
                "Unknown webhook channel, will auto-expire", channel_id=channel_id
            )
            return JSONResponse(
                {"status": "ignored_unknown_channel", "channel_id": channel_id}
            )

        # Process webhook for the specific connection
        try:
            # Get the connector instance
            connector = await connector_service._get_connector(connection.connection_id)
            if not connector:
                logger.error(
                    "Could not get connector for connection",
                    connection_id=connection.connection_id,
                )
                return JSONResponse(
                    {"status": "error", "reason": "connector_not_found"}
                )

            # Let the connector handle the webhook and return affected file IDs
            affected_files = await connector.handle_webhook(payload)

            if affected_files:
                logger.info(
                    "Webhook connection files affected",
                    connection_id=connection.connection_id,
                    affected_count=len(affected_files),
                )

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
                logger.info(
                    "Webhook general change detected, no specific files",
                    connection_id=connection.connection_id,
                )

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
            logger.error(
                "Failed to process webhook for connection",
                connection_id=connection.connection_id,
                error=str(e),
            )
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
        logger.error("Webhook processing failed", error=str(e))
        return JSONResponse(
            {"error": f"Webhook processing failed: {str(e)}"}, status_code=500
        )

async def connector_token(request: Request, connector_service, session_manager):
    """Get access token for connector API calls (e.g., Pickers)."""
    url_connector_type = request.path_params.get("connector_type")
    connection_id = request.query_params.get("connection_id")

    if not connection_id:
        return JSONResponse({"error": "connection_id is required"}, status_code=400)

    user = request.state.user

    try:
        # 1) Load the connection and verify ownership
        connection = await connector_service.connection_manager.get_connection(connection_id)
        if not connection or connection.user_id != user.user_id:
            return JSONResponse({"error": "Connection not found"}, status_code=404)

        # 2) Get the ACTUAL connector instance/type for this connection_id
        connector = await connector_service._get_connector(connection_id)
        if not connector:
            return JSONResponse(
                {"error": f"Connector not available - authentication may have failed for {url_connector_type}"},
                status_code=404,
            )

        real_type = getattr(connector, "type", None) or getattr(connection, "connector_type", None)
        if real_type is None:
            return JSONResponse({"error": "Unable to determine connector type"}, status_code=500)

        # Optional: warn if URL path type disagrees with real type
        if url_connector_type and url_connector_type != real_type:
            # You can downgrade this to debug if you expect cross-routing.
            return JSONResponse(
                {
                    "error": "Connector type mismatch",
                    "detail": {
                        "requested_type": url_connector_type,
                        "actual_type": real_type,
                        "hint": "Call the token endpoint using the correct connector_type for this connection_id.",
                    },
                },
                status_code=400,
            )

        # 3) Branch by the actual connector type
        # GOOGLE DRIVE (google-auth)
        if real_type == "google_drive" and hasattr(connector, "oauth"):
            await connector.oauth.load_credentials()
            if connector.oauth.creds and connector.oauth.creds.valid:
                expires_in = None
                try:
                    if connector.oauth.creds.expiry:
                        import time
                        expires_in = max(0, int(connector.oauth.creds.expiry.timestamp() - time.time()))
                except Exception:
                    expires_in = None

                return JSONResponse(
                    {
                        "access_token": connector.oauth.creds.token,
                        "expires_in": expires_in,
                    }
                )
            return JSONResponse({"error": "Invalid or expired credentials"}, status_code=401)

        # ONEDRIVE / SHAREPOINT (MSAL or custom)
        if real_type in ("onedrive", "sharepoint") and hasattr(connector, "oauth"):
            # Ensure cache/credentials are loaded before trying to use them
            try:
                # Prefer a dedicated is_authenticated() that loads cache internally
                if hasattr(connector.oauth, "is_authenticated"):
                    ok = await connector.oauth.is_authenticated()
                else:
                    # Fallback: try to load credentials explicitly if available
                    ok = True
                    if hasattr(connector.oauth, "load_credentials"):
                        ok = await connector.oauth.load_credentials()

                if not ok:
                    return JSONResponse({"error": "Not authenticated"}, status_code=401)

                # Now safe to fetch access token
                access_token = connector.oauth.get_access_token()
                # MSAL result has expiry, but we’re returning a raw token; keep expires_in None for simplicity
                return JSONResponse({"access_token": access_token, "expires_in": None})
            except ValueError as e:
                # Typical when acquire_token_silent fails (e.g., needs re-auth)
                return JSONResponse({"error": f"Failed to get access token: {str(e)}"}, status_code=401)
            except Exception as e:
                return JSONResponse({"error": f"Authentication error: {str(e)}"}, status_code=500)

        return JSONResponse({"error": "Token not available for this connector type"}, status_code=400)

    except Exception as e:
        logger.error("Error getting connector token", exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)
