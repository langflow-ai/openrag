from starlette.requests import Request
from starlette.responses import JSONResponse

from services.langflow_file_service import LangflowFileService
from utils.logging_config import get_logger

logger = get_logger(__name__)

async def delete_user_files(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        payload = await request.json()
        file_ids = payload.get("file_ids")
        if not file_ids or not isinstance(file_ids, list):
            return JSONResponse(
                {"error": "file_ids must be a non-empty list"}, status_code=400
            )

        errors = []
        for fid in file_ids:
            try:
                await langflow_file_service.delete_user_file(fid)
            except Exception as e:
                errors.append({"file_id": fid, "error": str(e)})

        status = 207 if errors else 200
        return JSONResponse(
            {
                "deleted": [
                    fid for fid in file_ids if fid not in [e["file_id"] for e in errors]
                ],
                "errors": errors,
            },
            status_code=status,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
