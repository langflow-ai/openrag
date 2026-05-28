from fastapi import Depends
from fastapi.responses import JSONResponse

from dependencies import get_current_user, get_task_service
from session_manager import User
from utils.telemetry import Category, MessageId, TelemetryClient


async def task_status(
    task_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Get the status of a specific task"""
    task_status_result = task_service.get_task_status(user.user_id, task_id)
    if not task_status_result:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return JSONResponse(task_status_result)


async def task_status_enhanced(
    task_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Get the status of a specific task with structured failure metadata."""
    task_status_result = task_service.get_task_status2(user.user_id, task_id)
    if not task_status_result:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return JSONResponse(task_status_result)


async def all_tasks(
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Get all tasks for the authenticated user"""
    tasks = task_service.get_all_tasks(user.user_id)
    return JSONResponse({"tasks": tasks})


async def all_tasks_enhanced(
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Get all tasks with structured failure metadata on failed files."""
    tasks = task_service.get_all_tasks2(user.user_id)
    return JSONResponse({"tasks": tasks})


async def cancel_task(
    task_id: str,
    task_service=Depends(get_task_service),
    user: User = Depends(get_current_user),
):
    """Cancel a task"""
    success = await task_service.cancel_task(user.user_id, task_id)
    if not success:
        await TelemetryClient.send_event(Category.TASK_OPERATIONS, MessageId.ORB_TASK_CANCEL_FAILED)
        return JSONResponse({"error": "Task not found or cannot be cancelled"}, status_code=400)

    await TelemetryClient.send_event(Category.TASK_OPERATIONS, MessageId.ORB_TASK_CANCELLED)
    return JSONResponse({"status": "cancelled", "task_id": task_id})
