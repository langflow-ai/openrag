from starlette.requests import Request
from starlette.responses import JSONResponse


async def task_status(request: Request, task_service, session_manager):
    """Get the status of a specific task"""
    task_id = request.path_params.get("task_id")
    user = request.state.user

    task_status_result = task_service.get_task_status(user.user_id, task_id)
    if not task_status_result:
        return JSONResponse({"error": "Task not found"}, status_code=404)

    return JSONResponse(task_status_result)


async def all_tasks(request: Request, task_service, session_manager):
    """Get all tasks for the authenticated user"""
    user = request.state.user
    tasks = task_service.get_all_tasks(user.user_id)
    return JSONResponse({"tasks": tasks})


async def cancel_task(request: Request, task_service, session_manager):
    """Cancel a task"""
    task_id = request.path_params.get("task_id")
    user = request.state.user

    success = await task_service.cancel_task(user.user_id, task_id)
    if not success:
        return JSONResponse(
            {"error": "Task not found or cannot be cancelled"}, status_code=400
        )

    return JSONResponse({"status": "cancelled", "task_id": task_id})
