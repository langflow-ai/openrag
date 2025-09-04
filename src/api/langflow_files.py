from starlette.requests import Request
from starlette.responses import JSONResponse

from services.langflow_file_service import LangflowFileService


async def upload_user_file(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        print("[DEBUG] upload_user_file endpoint called")
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            print("[ERROR] No file provided in upload request")
            return JSONResponse({"error": "Missing file"}, status_code=400)

        print(
            f"[DEBUG] Processing file: {upload_file.filename}, size: {upload_file.size}"
        )

        # starlette UploadFile provides file-like; httpx needs (filename, file, content_type)
        content = await upload_file.read()
        file_tuple = (
            upload_file.filename,
            content,
            upload_file.content_type or "application/octet-stream",
        )

        jwt_token = getattr(request.state, "jwt_token", None)
        print(f"[DEBUG] JWT token present: {jwt_token is not None}")

        print("[DEBUG] Calling langflow_file_service.upload_user_file...")
        result = await langflow_file_service.upload_user_file(
            file_tuple, jwt_token=jwt_token
        )
        print(f"[DEBUG] Upload successful: {result}")
        return JSONResponse(result, status_code=201)
    except Exception as e:
        print(f"[ERROR] upload_user_file endpoint failed: {type(e).__name__}: {e}")
        import traceback

        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        return JSONResponse({"error": str(e)}, status_code=500)


async def run_ingestion(
    request: Request, langflow_file_service: LangflowFileService, session_manager
):
    try:
        payload = await request.json()
        file_ids = payload.get("file_ids")
        file_paths = payload.get("file_paths") or []
        session_id = payload.get("session_id")
        tweaks = payload.get("tweaks")

        # We assume file_paths is provided. If only file_ids are provided, client would need to resolve to paths via Files API (not implemented here).
        if not file_paths and not file_ids:
            return JSONResponse(
                {"error": "Provide file_paths or file_ids"}, status_code=400
            )

        # Include user JWT if available
        jwt_token = getattr(request.state, "jwt_token", None)

        result = await langflow_file_service.run_ingestion_flow(
            file_paths=file_paths or [],
            session_id=session_id,
            tweaks=tweaks,
            jwt_token=jwt_token,
        )
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
