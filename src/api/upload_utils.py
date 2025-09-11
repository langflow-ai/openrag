from typing import List

from starlette.requests import Request


async def extract_user_context(request: Request) -> dict:
    """Extract user/auth context from request.state. Honors no-auth mode."""
    from config.settings import is_no_auth_mode

    user = getattr(request.state, "user", None)
    jwt_token = getattr(request.state, "jwt_token", None)

    if is_no_auth_mode():
        return {
            "owner_user_id": None,
            "owner_name": None,
            "owner_email": None,
            "jwt_token": None,
        }

    return {
        "owner_user_id": getattr(user, "user_id", None),
        "owner_name": getattr(user, "name", None),
        "owner_email": getattr(user, "email", None),
        "jwt_token": jwt_token,
    }


async def create_temp_files_from_form_files(upload_files: List) -> list[str]:
    """Persist UploadFile items to temp files; return list of paths."""
    import tempfile
    import os

    temp_file_paths: list[str] = []
    for upload_file in upload_files:
        content = await upload_file.read()
        safe_filename = (
            upload_file.filename.replace(" ", "_").replace("/", "_")
            if getattr(upload_file, "filename", None)
            else "uploaded"
        )
        fd, temp_path = tempfile.mkstemp(suffix=f"_{safe_filename}")
        with os.fdopen(fd, "wb") as temp_file:
            temp_file.write(content)
        temp_file_paths.append(temp_path)
    return temp_file_paths

