import os
from starlette.responses import JSONResponse
from config.settings import LANGFLOW_URL, FLOW_ID, LANGFLOW_PUBLIC_URL

async def get_settings(request, session_manager):
    """Get application settings"""
    try:
        # Return public settings that are safe to expose to frontend
        settings = {
            "langflow_url": LANGFLOW_URL,
            "flow_id": FLOW_ID,
            "langflow_public_url": LANGFLOW_PUBLIC_URL,
        }
        
        # Only expose edit URL when a public URL is configured
        if LANGFLOW_PUBLIC_URL and FLOW_ID:
            settings["langflow_edit_url"] = f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{FLOW_ID}"
        
        return JSONResponse(settings)
        
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to retrieve settings: {str(e)}"},
            status_code=500
        )
