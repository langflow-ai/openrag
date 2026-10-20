#!/usr/bin/env python3
"""Serve Langflow directly below ``OPENRAG_LANGFLOW_BASE_PATH``.

Langflow's ``LANGFLOW_ROOT_PATH`` is deliberately designed for a reverse proxy
which removes the prefix before requests reach the application.  This wrapper
keeps the prefix in direct requests and removes it at the ASGI boundary, so
``/langflow/api/v1/...`` reaches Langflow's normal ``/api/v1/...`` route.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class DirectBasePathApp:
    """Expose one ASGI application at both its root and a direct URL prefix."""

    def __init__(
        self, app: Callable[[Scope, Receive, Send], Awaitable[None]], base_path: str
    ) -> None:
        self.app = app
        self.base_path = base_path
        self._base_path_bytes = base_path.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path != self.base_path and not path.startswith(f"{self.base_path}/"):
            await self.app(scope, receive, send)
            return

        child_scope = dict(scope)
        child_scope["path"] = path[len(self.base_path) :] or "/"
        child_scope["root_path"] = f"{scope.get('root_path', '')}{self.base_path}"
        raw_path = scope.get("raw_path")
        if isinstance(raw_path, bytes):
            child_scope["raw_path"] = raw_path[len(self._base_path_bytes) :] or b"/"
        await self.app(child_scope, receive, send)


def main() -> None:
    base_path = os.environ.get("OPENRAG_LANGFLOW_BASE_PATH", "")
    if not base_path:
        msg = "OPENRAG_LANGFLOW_BASE_PATH must be set by langflow-entrypoint"
        raise RuntimeError(msg)

    # Importing Langflow's CLI and replacing this module global retains its
    # complete normal startup path (settings, preflight checks, workers, and
    # lifecycle) while changing only the ASGI application it serves.
    from langflow import __main__ as langflow_cli

    setup_app = langflow_cli.setup_app

    def setup_app_at_base_path(*args: Any, **kwargs: Any) -> DirectBasePathApp:
        return DirectBasePathApp(setup_app(*args, **kwargs), base_path)

    langflow_cli.setup_app = setup_app_at_base_path
    sys.argv = ["langflow", "run", *sys.argv[1:]]
    langflow_cli.app()


if __name__ == "__main__":
    main()
