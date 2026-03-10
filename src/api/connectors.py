from typing import Any, List, Optional

from fastapi import Depends, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse, PlainTextResponse
from connectors.sharepoint.utils import is_valid_sharepoint_url
from config.settings import get_index_name
from utils.logging_config import get_logger
from utils.telemetry import TelemetryClient, Category, MessageId
from dependencies import get_connector_service, get_session_manager, get_current_user
from session_manager import User

logger = get_logger(__name__)


async def get_synced_file_ids_for_connector(
    connector_type: str,
    user_id: str,
    session_manager,
    jwt_token: str = None,
) -> tuple:
    """
    Query OpenSearch for unique document_id values where connector_type matches.
    Returns tuple of (file_ids, filenames) - use file_ids if available, else filenames as fallback.
    
    Note: Langflow-ingested files may not have document_id stored. In that case,
    filenames are returned for filename-based filtering during sync.
    """
    try:
        opensearch_client = session_manager.get_user_opensearch_client(user_id, jwt_token)
        
        # Query for both document_id and filename aggregations
        query_body = {
            "size": 0,
            "query": {
                "term": {
                    "connector_type": connector_type
                }
            },
            "aggs": {
                "unique_document_ids": {
                    "terms": {
                        "field": "document_id",
                        "size": 10000
                    }
                },
                "unique_filenames": {
                    "terms": {
                        "field": "filename",
                        "size": 10000
                    }
                }
            }
        }
        
        result = await opensearch_client.search(
            index=get_index_name(),
            body=query_body
        )
        
        # Get document_ids (preferred - these are the actual connector file IDs)
        doc_id_buckets = result.get("aggregations", {}).get("unique_document_ids", {}).get("buckets", [])
        file_ids = [bucket["key"] for bucket in doc_id_buckets if bucket["key"]]
        
        # Get filenames as fallback
        filename_buckets = result.get("aggregations", {}).get("unique_filenames", {}).get("buckets", [])
        filenames = [bucket["key"] for bucket in filename_buckets if bucket["key"]]
        
        logger.debug(
            "Found synced files for connector",
            connector_type=connector_type,
            file_ids_count=len(file_ids),
            filenames_count=len(filenames),
        )
        
        return file_ids, filenames
        
    except Exception as e:
        logger.error(
            "Failed to get synced file IDs",
            connector_type=connector_type,
            error=str(e),
        )
        return [], []



class ConnectorSyncBody(BaseModel):
    max_files: Optional[int] = None
    selected_files: Optional[List[Any]] = None


async def list_connectors(
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """List available connector types with metadata"""
    try:
        connector_types = (
            connector_service.connection_manager.get_available_connector_types()
        )
        return JSONResponse({"connectors": connector_types})
    except Exception as e:
        logger.info("Error listing connectors", error=str(e))
        return JSONResponse({"connectors": []})


async def connector_sync(
    connector_type: str,
    body: ConnectorSyncBody,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """Sync files from all active connections of a connector type"""
    max_files = body.max_files
    selected_files_raw = body.selected_files
    selected_files = None
    file_infos = None
    if selected_files_raw:
        if isinstance(selected_files_raw[0], str):
            # Legacy format: just IDs
            selected_files = selected_files_raw
        else:
            # New format: file objects with metadata
            selected_files = [f.get("id") for f in selected_files_raw if f.get("id")]
            file_infos = selected_files_raw

    try:
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_START)
        logger.debug(
            "Starting connector sync",
            connector_type=connector_type,
            max_files=max_files,
        )
        jwt_token = user.jwt_token

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
            # Explicit files selected (e.g., from file picker) - sync those specific files
            from .documents import _ensure_index_exists
            await _ensure_index_exists()
            task_id = await connector_service.sync_specific_files(
                working_connection.connection_id,
                user.user_id,
                selected_files,
                jwt_token=jwt_token,
                file_infos=file_infos,
            )
        else:
            # No files specified - sync only files already in OpenSearch for this connector
            # This ensures deleted files stay deleted
            existing_file_ids, existing_filenames = await get_synced_file_ids_for_connector(
                connector_type=connector_type,
                user_id=user.user_id,
                session_manager=session_manager,
                jwt_token=jwt_token,
            )
            
            if not existing_file_ids and not existing_filenames:
                return JSONResponse(
                    {
                        "status": "no_files",
                        "message": f"No {connector_type} files to sync. Add files from the connector first.",
                    },
                    status_code=200,
                )
            
            # If we have document_ids (connector file IDs), use sync_specific_files
            # Otherwise, use filename filtering with sync_connector_files
            if existing_file_ids:
                logger.info(
                    "Syncing specific files by document_id",
                    connector_type=connector_type,
                    file_count=len(existing_file_ids),
                )
                task_id = await connector_service.sync_specific_files(
                    working_connection.connection_id,
                    user.user_id,
                    existing_file_ids,
                    jwt_token=jwt_token,
                )
            else:
                # Fallback: use filename filtering (for Langflow-ingested files without document_id)
                logger.info(
                    "Syncing files by filename filter (document_id not available)",
                    connector_type=connector_type,
                    filename_count=len(existing_filenames),
                )
                task_id = await connector_service.sync_connector_files(
                    working_connection.connection_id,
                    user.user_id,
                    max_files=None,
                    jwt_token=jwt_token,
                    filename_filter=set(existing_filenames),
                )
        task_ids = [task_id]
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_COMPLETE)
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
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_FAILED)
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


async def connector_status(
    connector_type: str,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Get connector status for authenticated user"""

    # Get connections for this connector type and user
    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, connector_type=connector_type
    )

    # Get the connector for each connection and verify authentication
    connection_details = {}
    verified_active_connections = []
    
    for connection in connections:
        try:
            connector = await connector_service._get_connector(connection.connection_id)
            if connector is not None:
                # Actually verify the connection by trying to authenticate
                is_authenticated = await connector.authenticate()
                
                # Get base URL if available (for SharePoint/OneDrive connectors)
                base_url = None
                if hasattr(connector, 'base_url'):
                    base_url = connector.base_url
                    logger.debug(f"connector_status: Got base_url from connector.base_url: {base_url}")
                elif hasattr(connector, 'sharepoint_url'):
                    base_url = connector.sharepoint_url  # Backward compatibility
                    logger.debug(f"connector_status: Got base_url from connector.sharepoint_url: {base_url}")
                else:
                    logger.debug(f"connector_status: Connector has no base_url or sharepoint_url attribute")
                
                connection_details[connection.connection_id] = {
                    "client_id": connector.get_client_id(),
                    "is_authenticated": is_authenticated,
                    "base_url": base_url,
                }
                if is_authenticated and connection.is_active:
                    verified_active_connections.append(connection)
            else:
                connection_details[connection.connection_id] = {
                    "client_id": None,
                    "is_authenticated": False,
                    "base_url": None,
                }
        except Exception as e:
            logger.warning(
                "Could not verify connector authentication",
                connection_id=connection.connection_id,
                error=str(e),
            )
            connection_details[connection.connection_id] = {
                "client_id": None,
                "is_authenticated": False,
                "base_url": None,
            }

    # Only count connections that are both active AND actually authenticated
    has_authenticated_connection = len(verified_active_connections) > 0

    return JSONResponse(
        {
            "connector_type": connector_type,
            "authenticated": has_authenticated_connection,
            "status": "connected" if has_authenticated_connection else "not_connected",
            "connections": [
                {
                    "connection_id": conn.connection_id,
                    "name": conn.name,
                    "client_id": connection_details.get(conn.connection_id, {}).get("client_id"),
                    "is_active": conn.is_active and connection_details.get(conn.connection_id, {}).get("is_authenticated", False),
                    "is_authenticated": connection_details.get(conn.connection_id, {}).get("is_authenticated", False),
                    "base_url": connection_details.get(conn.connection_id, {}).get("base_url"),
                    "created_at": conn.created_at.isoformat(),
                    "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
                }
                for conn in connections
            ],
        }
    )


async def connector_webhook(
    connector_type: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
):
    """Handle webhook notifications from any connector type"""

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
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_WEBHOOK_RECV)
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
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_WEBHOOK_FAILED)
        return JSONResponse(
            {"error": f"Webhook processing failed: {str(e)}"}, status_code=500
        )

async def connector_disconnect(
    connector_type: str,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Disconnect a connector by deleting its connection"""

    try:
        # Get connections for this connector type and user
        connections = await connector_service.connection_manager.list_connections(
            user_id=user.user_id, connector_type=connector_type
        )

        if not connections:
            return JSONResponse(
                {"error": f"No {connector_type} connections found"},
                status_code=404,
            )

        # Delete all connections for this connector type and user
        deleted_count = 0
        for connection in connections:
            try:
                # Get the connector to cleanup any subscriptions
                connector = await connector_service._get_connector(connection.connection_id)
                if connector and hasattr(connector, 'cleanup_subscription'):
                    subscription_id = connection.config.get("webhook_channel_id")
                    if subscription_id:
                        try:
                            await connector.cleanup_subscription(subscription_id)
                        except Exception as e:
                            logger.warning(
                                "Failed to cleanup subscription",
                                connection_id=connection.connection_id,
                                error=str(e),
                            )
            except Exception as e:
                logger.warning(
                    "Could not get connector for cleanup",
                    connection_id=connection.connection_id,
                    error=str(e),
                )

            # Delete the connection
            success = await connector_service.connection_manager.delete_connection(
                connection.connection_id
            )
            if success:
                deleted_count += 1

        logger.info(
            "Disconnected connector",
            connector_type=connector_type,
            user_id=user.user_id,
            deleted_count=deleted_count,
        )

        return JSONResponse(
            {
                "status": "disconnected",
                "connector_type": connector_type,
                "deleted_connections": deleted_count,
            }
        )

    except Exception as e:
        logger.error(
            "Failed to disconnect connector",
            connector_type=connector_type,
            error=str(e),
        )
        return JSONResponse(
            {"error": f"Disconnect failed: {str(e)}"},
            status_code=500,
        )


async def sync_all_connectors(
    connector_service=Depends(get_connector_service),
    session_manager=Depends(get_session_manager),
    user: User = Depends(get_current_user),
):
    """
    Sync files from all active cloud connector connections.
    """
    try:
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_START)
        jwt_token = user.jwt_token

        # Cloud connector types to sync
        cloud_connector_types = ["google_drive", "onedrive", "sharepoint"]
        
        all_task_ids = []
        synced_connectors = []
        skipped_connectors = []
        errors = []

        for connector_type in cloud_connector_types:
            try:
                # First, get existing file IDs/filenames from OpenSearch for this connector type
                existing_file_ids, existing_filenames = await get_synced_file_ids_for_connector(
                    connector_type=connector_type,
                    user_id=user.user_id,
                    session_manager=session_manager,
                    jwt_token=jwt_token,
                )
                
                if not existing_file_ids and not existing_filenames:
                    logger.debug(
                        "No existing files in OpenSearch for connector type, skipping",
                        connector_type=connector_type,
                    )
                    skipped_connectors.append(connector_type)
                    continue

                # Get all active connections for this connector type and user
                connections = await connector_service.connection_manager.list_connections(
                    user_id=user.user_id, connector_type=connector_type
                )

                active_connections = [conn for conn in connections if conn.is_active]
                if not active_connections:
                    logger.debug(
                        "No active connections for connector type",
                        connector_type=connector_type,
                    )
                    continue

                # Find the first connection that actually works
                working_connection = None
                for connection in active_connections:
                    try:
                        connector = await connector_service.get_connector(connection.connection_id)
                        if connector and await connector.authenticate():
                            working_connection = connection
                            break
                    except Exception as e:
                        logger.debug(
                            "Connection validation failed",
                            connection_id=connection.connection_id,
                            error=str(e),
                        )
                        continue

                if not working_connection:
                    logger.debug(
                        "No working connection for connector type",
                        connector_type=connector_type,
                    )
                    continue

                # Sync using document_ids if available, else use filename filter
                if existing_file_ids:
                    logger.info(
                        "Syncing specific files by document_id",
                        connector_type=connector_type,
                        file_count=len(existing_file_ids),
                    )
                    task_id = await connector_service.sync_specific_files(
                        working_connection.connection_id,
                        user.user_id,
                        existing_file_ids,
                        jwt_token=jwt_token,
                    )
                else:
                    # Fallback: use filename filtering
                    logger.info(
                        "Syncing files by filename filter",
                        connector_type=connector_type,
                        filename_count=len(existing_filenames),
                    )
                    task_id = await connector_service.sync_connector_files(
                        working_connection.connection_id,
                        user.user_id,
                        max_files=None,
                        jwt_token=jwt_token,
                        filename_filter=set(existing_filenames),
                    )
                    
                all_task_ids.append(task_id)
                synced_connectors.append(connector_type)
                logger.info(
                    "Started sync for connector type",
                    connector_type=connector_type,
                    task_id=task_id,
                    file_count=len(existing_file_ids) if existing_file_ids else len(existing_filenames),
                )

            except Exception as e:
                logger.error(
                    "Failed to sync connector type",
                    connector_type=connector_type,
                    error=str(e),
                )
                errors.append({"connector_type": connector_type, "error": str(e)})

        if not all_task_ids and not errors:
            if skipped_connectors:
                return JSONResponse(
                    {
                        "status": "no_files",
                        "message": "No files to sync. Add files from cloud connectors first.",
                        "skipped_connectors": skipped_connectors,
                    },
                    status_code=200,
                )
            return JSONResponse(
                {"error": "No active cloud connector connections found"},
                status_code=404,
            )

        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_COMPLETE)
        return JSONResponse(
            {
                "task_ids": all_task_ids,
                "status": "sync_started",
                "message": f"Started syncing files from {len(synced_connectors)} cloud connector(s)",
                "synced_connectors": synced_connectors,
                "skipped_connectors": skipped_connectors if skipped_connectors else None,
                "errors": errors if errors else None,
            },
            status_code=201,
        )

    except Exception as e:
        logger.error("Sync all connectors failed", error=str(e))
        await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_SYNC_FAILED)
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)


async def connector_token(
    connector_type: str,
    connection_id: str,
    request: Request,
    connector_service=Depends(get_connector_service),
    user: User = Depends(get_current_user),
):
    """Get access token for connector API calls (e.g., Pickers)."""
    url_connector_type = connector_type

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

                # Check if a specific resource is requested (for SharePoint File Picker v8)
                # The File Picker requires a token with SharePoint as the audience, not Graph
                resource = request.query_params.get("resource")

                if resource and is_valid_sharepoint_url(resource):
                    # SharePoint File Picker v8 needs a SharePoint-scoped token
                    logger.info(f"Acquiring SharePoint-scoped token for resource: {resource}")
                    if hasattr(connector.oauth, "get_access_token_for_resource"):
                        access_token = connector.oauth.get_access_token_for_resource(resource)
                    else:
                        # Fallback for connectors without resource-specific token support
                        access_token = connector.oauth.get_access_token()
                else:
                    # Default: Microsoft Graph token
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
