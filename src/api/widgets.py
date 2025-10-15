"""Widget generation API endpoints."""
import json
import uuid
from starlette.requests import Request
from starlette.responses import JSONResponse
from services.widget_service import WidgetService
from session_manager import SessionManager
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def generate_widget(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """Generate a new widget from a prompt, or iterate on an existing widget."""
    try:
        # Get request data
        data = await request.json()
        prompt = data.get("prompt")
        base_widget_id = data.get("base_widget_id")  # Optional - for iterations

        if not prompt:
            return JSONResponse(
                {"error": "Prompt is required"}, status_code=400
            )

        # Get user from request context (added by auth middleware)
        user = request.state.user
        user_id = user.user_id if user else "anonymous"

        # Generate widget ID
        widget_id = str(uuid.uuid4())

        # Generate the widget (optionally based on an existing one)
        result = await widget_service.generate_widget(
            widget_id=widget_id,
            prompt=prompt,
            user_id=user_id,
            base_widget_id=base_widget_id
        )

        logger.info(
            "Widget generated via API",
            widget_id=widget_id,
            user_id=user_id,
            is_iteration=bool(base_widget_id)
        )

        return JSONResponse(result)

    except Exception as e:
        logger.error("Widget generation failed", error=str(e))
        return JSONResponse(
            {"error": f"Widget generation failed: {str(e)}"}, status_code=500
        )


async def list_widgets(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """List all widgets for the current user."""
    try:
        user = request.state.user
        user_id = user.user_id if user else "anonymous"

        widgets = await widget_service.list_widgets(user_id=user_id)

        return JSONResponse({"widgets": widgets})

    except Exception as e:
        logger.error("Failed to list widgets", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_widget(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """Get widget details by ID."""
    try:
        widget_id = request.path_params.get("widget_id")

        if not widget_id:
            return JSONResponse({"error": "Widget ID is required"}, status_code=400)

        widget = await widget_service.get_widget(widget_id=widget_id)

        if not widget:
            return JSONResponse({"error": "Widget not found"}, status_code=404)

        return JSONResponse(widget)

    except Exception as e:
        logger.error("Failed to get widget", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_widget(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """Delete a widget."""
    try:
        widget_id = request.path_params.get("widget_id")

        if not widget_id:
            return JSONResponse({"error": "Widget ID is required"}, status_code=400)

        user = request.state.user
        user_id = user.user_id if user else "anonymous"

        success = await widget_service.delete_widget(
            widget_id=widget_id, user_id=user_id
        )

        if not success:
            return JSONResponse({"error": "Widget not found"}, status_code=404)

        return JSONResponse({"status": "success", "widget_id": widget_id})

    except Exception as e:
        logger.error("Failed to delete widget", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def build_widget(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """Trigger a build for a specific widget."""
    try:
        widget_id = request.path_params.get("widget_id")

        if not widget_id:
            return JSONResponse({"error": "Widget ID is required"}, status_code=400)

        # Trigger the build
        await widget_service._build_widget(widget_id)

        logger.info("Widget build requested", widget_id=widget_id)

        return JSONResponse({
            "status": "success",
            "message": "Widget build triggered",
            "widget_id": widget_id
        })

    except Exception as e:
        logger.error("Failed to trigger widget build", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)


async def rename_widget(
    request: Request, widget_service: WidgetService, session_manager: SessionManager
):
    """Rename a widget by updating its title."""
    try:
        widget_id = request.path_params.get("widget_id")

        if not widget_id:
            return JSONResponse({"error": "Widget ID is required"}, status_code=400)

        # Get request data
        data = await request.json()
        title = data.get("title")

        if not title:
            return JSONResponse({"error": "Title is required"}, status_code=400)

        # Get user from request context
        user = request.state.user
        user_id = user.user_id if user else "anonymous"

        # Rename the widget
        success = await widget_service.rename_widget(
            widget_id=widget_id, title=title, user_id=user_id
        )

        if not success:
            return JSONResponse({"error": "Widget not found"}, status_code=404)

        logger.info("Widget renamed", widget_id=widget_id, title=title, user_id=user_id)

        return JSONResponse({"status": "success", "widget_id": widget_id, "title": title})

    except Exception as e:
        logger.error("Failed to rename widget", error=str(e))
        return JSONResponse({"error": str(e)}, status_code=500)
