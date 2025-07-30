from starlette.requests import Request
from starlette.responses import JSONResponse

async def connector_sync(request: Request, connector_service, session_manager):
    """Sync files from a connector connection"""
    data = await request.json()
    connection_id = data.get("connection_id")
    max_files = data.get("max_files")
    
    if not connection_id:
        return JSONResponse({"error": "connection_id is required"}, status_code=400)
    
    try:
        print(f"[DEBUG] Starting connector sync for connection_id={connection_id}, max_files={max_files}")
        
        # Verify user owns this connection
        user = request.state.user
        print(f"[DEBUG] User: {user.user_id}")
        
        connection_config = await connector_service.connection_manager.get_connection(connection_id)
        print(f"[DEBUG] Got connection config: {connection_config is not None}")
        
        if not connection_config:
            return JSONResponse({"error": "Connection not found"}, status_code=404)
        
        if connection_config.user_id != user.user_id:
            return JSONResponse({"error": "Access denied"}, status_code=403)
        
        print(f"[DEBUG] About to call sync_connector_files")
        task_id = await connector_service.sync_connector_files(connection_id, user.user_id, max_files)
        print(f"[DEBUG] Got task_id: {task_id}")
        
        return JSONResponse({
                "task_id": task_id,
                "status": "sync_started",
                "message": f"Started syncing files from connection {connection_id}"
            },
            status_code=201
        )
        
    except Exception as e:
        import sys
        import traceback
        
        error_msg = f"[ERROR] Connector sync failed: {str(e)}"
        print(error_msg, file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        
        return JSONResponse({"error": f"Sync failed: {str(e)}"}, status_code=500)

async def connector_status(request: Request, connector_service, session_manager):
    """Get connector status for authenticated user"""
    connector_type = request.path_params.get("connector_type", "google_drive")
    user = request.state.user
    
    # Get connections for this connector type and user
    connections = await connector_service.connection_manager.list_connections(
        user_id=user.user_id, 
        connector_type=connector_type
    )
    
    # Check if there are any active connections
    active_connections = [conn for conn in connections if conn.is_active]
    has_authenticated_connection = len(active_connections) > 0
    
    return JSONResponse({
        "connector_type": connector_type,
        "authenticated": has_authenticated_connection,
        "status": "connected" if has_authenticated_connection else "not_connected",
        "connections": [
            {
                "connection_id": conn.connection_id,
                "name": conn.name,
                "is_active": conn.is_active,
                "created_at": conn.created_at.isoformat(),
                "last_sync": conn.last_sync.isoformat() if conn.last_sync else None
            }
            for conn in connections
        ]
    })