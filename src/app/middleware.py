"""ASGI middleware for request correlation IDs and structured access logs."""

import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

from utils.logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware:
    """Pure ASGI middleware that assigns a correlation ID to every request and
    emits a single structured [API] log line with method, path, status code,
    and duration after the response is sent.

    Using pure ASGI (not BaseHTTPMiddleware) so structlog contextvars bound
    inside endpoint handlers propagate back correctly to this middleware.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import structlog as _structlog

        _structlog.contextvars.clear_contextvars()

        headers_dict = dict(scope.get("headers", []))
        request_id = headers_dict.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        path = scope.get("path", "")
        method = scope.get("method", "")

        _structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
        )

        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            level = "warning" if status_code >= 500 else "info"
            getattr(logger, level)(
                "[API] Request",
                status_code=status_code,
                duration_ms=duration_ms,
            )
            _structlog.contextvars.clear_contextvars()
