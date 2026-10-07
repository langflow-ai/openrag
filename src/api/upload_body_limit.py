"""Stop reading an ingest upload once the body exceeds the configured limit.

``upload_ingest_router`` can only look at ``UploadFile.size`` after FastAPI
has parsed the multipart body and stored every part. A body far past the
per-file limit would be fully received first. This middleware counts the
bytes as they arrive on the ingest routes and stops the read once they pass
the per-file limit plus a fixed allowance for the multipart envelope.

That cap is the whole request. Both ingest routes accept several files, but
the body is one stream, so the read cannot tell two valid files from one
file that is already too big. Two files that are each under the per-file
limit still stop the read when their total passes it. Folder uploads are
split to stay under that total. Other clients have to send fewer files per
request. Raising the cap to a whole batch would let one oversized file be
stored before the per-file check could reject it.

The allowance is what lets a single file at the limit, plus its boundary and
headers, still reach the per-file check, which is the response that names
the file. A larger body never gets that far.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Boundary, part headers, and the small form fields that ride with the file
# (settings, tweaks). One mebibyte is far more than that envelope and far
# less than another copy of the file.
UPLOAD_BODY_OVERHEAD_BYTES = 1024 * 1024

# Routes whose handler is upload_ingest_router. The public route parses the
# body itself and then calls the router, so the read has to be capped here.
UPLOAD_INGEST_PATHS = frozenset({"/router/upload_ingest", "/v1/documents/ingest"})


def upload_request_body_limit_bytes() -> int:
    # Read at call time so a test (or a reload) sees the current setting.
    from config.settings import MAX_UPLOAD_SIZE_BYTES

    return MAX_UPLOAD_SIZE_BYTES + UPLOAD_BODY_OVERHEAD_BYTES


def limited_receive(receive: Receive, max_bytes: int) -> Receive:
    """Wrap an ASGI receive so the body is not forwarded past ``max_bytes``."""
    received = 0

    async def wrapped() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] != "http.request":
            return message
        chunk = message.get("body") or b""
        received += len(chunk)
        if received > max_bytes:
            # HTTPException, not a bare Exception: FastAPI turns every other
            # error raised while parsing the form into a 400, and re-raises
            # this one so the client gets a 413.
            from config.settings import MAX_UPLOAD_SIZE_MB

            raise HTTPException(
                status_code=413,
                detail=(
                    f"Upload too large. One ingest request cannot exceed {MAX_UPLOAD_SIZE_MB} MB "
                    "plus multipart overhead, so the upload was stopped while it was still "
                    "being received. Send fewer or smaller files."
                ),
            )
        return message

    return wrapped


class UploadBodyLimitMiddleware:
    """Pure ASGI. Caps the request body on the ingest routes only."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        if scope.get("path") not in UPLOAD_INGEST_PATHS:
            await self.app(scope, receive, send)
            return
        await self.app(scope, limited_receive(receive, upload_request_body_limit_bytes()), send)
