from starlette.responses import JSONResponse
from config.settings import (
    LANGFLOW_URL,
    LANGFLOW_CHAT_FLOW_ID,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_PUBLIC_URL,
)


async def get_settings(request, session_manager):
    """Get application settings"""
    try:
        # Return public settings that are safe to expose to frontend
        settings = {
            "langflow_url": LANGFLOW_URL,
            "flow_id": LANGFLOW_CHAT_FLOW_ID,
            "ingest_flow_id": LANGFLOW_INGEST_FLOW_ID,
            "langflow_public_url": LANGFLOW_PUBLIC_URL,
        }

        # Only expose edit URLs when a public URL is configured
        if LANGFLOW_PUBLIC_URL and LANGFLOW_CHAT_FLOW_ID:
            settings["langflow_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_CHAT_FLOW_ID}"
            )

        if LANGFLOW_PUBLIC_URL and LANGFLOW_INGEST_FLOW_ID:
            settings["langflow_ingest_edit_url"] = (
                f"{LANGFLOW_PUBLIC_URL.rstrip('/')}/flow/{LANGFLOW_INGEST_FLOW_ID}"
            )

        # Fetch ingestion flow validation and available settings
        if LANGFLOW_INGEST_FLOW_ID:
            try:
                from services.langflow_file_service import LangflowFileService
                from services.flow_validation_context import set_flow_components

                langflow_service = LangflowFileService()

                # Validate the flow and get component information
                component_info = await langflow_service.validate_ingestion_flow()

                # Set in context for other endpoints to use
                user = getattr(request.state, "user", None)
                user_id = user.user_id if user else "anonymous"
                await set_flow_components(user_id, component_info)

                # Add flow validation results to settings
                settings["flow_validation"] = component_info.to_dict()

            except Exception as e:
                print(f"[WARNING] Failed to validate ingestion flow: {e}")
                # Continue without flow validation data
                settings["flow_validation"] = {
                    "components": {},
                    "validation": {"is_valid": False, "error": str(e)},
                    "available_ui_settings": {},
                }

        return JSONResponse(settings)

    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to retrieve settings: {str(e)}"}, status_code=500
        )
