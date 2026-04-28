from typing import List, Dict, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config.settings import clients
from utils.logging_config import get_logger


logger = get_logger(__name__)


class LangflowMCPService:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _list_mcp_servers_with_retry(self) -> List[Dict[str, Any]]:
        """Internal method with retry logic for listing MCP servers."""
        response = await clients.langflow_request(
            method="GET",
            endpoint="/api/v2/mcp/servers",
            params={"action_count": "false"},
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        logger.warning(
            "Unexpected response format for MCP servers list",
            data_type=type(data).__name__,
        )
        return []

    async def list_mcp_servers(self) -> List[Dict[str, Any]]:
        """Fetch list of MCP servers from Langflow (v2 API).

        Includes retry logic to handle startup timing issues.
        """
        try:
            return await self._list_mcp_servers_with_retry()
        except Exception as e:
            logger.error("Failed to list MCP servers after retries", error=str(e))
            return []

    async def get_mcp_server(self, server_name: str) -> Dict[str, Any]:
        """Get MCP server configuration by name."""
        response = await clients.langflow_request(
            method="GET",
            endpoint=f"/api/v2/mcp/servers/{server_name}",
        )
        response.raise_for_status()
        return response.json()

    def _parse_stdio_args(self, args: List[str]) -> tuple[str | None, Dict[str, str]]:
        """Extract URL and headers from stdio args.

        Args format: [URL, "--headers", key1, value1, "--headers", key2, value2, ...]
        or: ["--transport", "sse", URL, "--headers", ...]
        Returns: (url, headers_dict)
        """
        if not isinstance(args, list) or not args:
            return None, {}

        url: str | None = None
        headers: Dict[str, str] = {}
        url_index: int = -1

        # Find the URL by scanning for http:// or https://
        for idx, arg in enumerate(args):
            if isinstance(arg, str) and (
                arg.startswith("http://") or arg.startswith("https://")
            ):
                url = arg
                url_index = idx
                break

        # Parse --headers triplets: --headers key value
        i = 0
        while i < len(args):
            # Skip the URL element
            if i == url_index:
                i += 1
                continue

            token = args[i]
            if token == "--headers" and i + 2 < len(args):
                header_key = args[i + 1]
                header_value = args[i + 2]
                if isinstance(header_key, str) and isinstance(header_value, str):
                    headers[header_key] = header_value
                i += 3
            else:
                i += 1

        return url, headers

    def _is_convertible_to_streamable_http(self, server_config: Dict[str, Any]) -> bool:
        """Check if stdio server can be converted to streamable HTTP.

        Returns True if:
        - Server has 'command' field (stdio mode)
        - Args contain a URL (starting with http:// or https://)
        """
        if not server_config.get("command"):
            return False

        args = server_config.get("args", [])
        if not isinstance(args, list) or not args:
            return False

        # Scan args to find a URL (may not be at position 0)
        for arg in args:
            if not isinstance(arg, str):
                continue
            if arg.startswith("http://") or arg.startswith("https://"):
                # We convert any stdio server with a URL to streamable HTTP
                return True

        return False

    def _is_streamable_http_mode(self, server_config: Dict[str, Any]) -> bool:
        """Check if server is in streamable HTTP mode (has url field)."""
        return bool(server_config.get("url"))

    def _patch_url_with_langflow_url(self, url: str) -> str:
        """Patch the URL to include the Langflow URL.

        Args:
            url: The URL to patch
        Returns:
            The patched URL
        """
        import os
        import re

        langflow_url = os.environ.get("LANGFLOW_URL")
        if not langflow_url:
            return url

        # Pattern to match 'http://localhost', 'https://localhost', WITH optional :<port>
        pattern = re.compile(r"https?://localhost(:\d+)?", re.IGNORECASE)

        if pattern.search(url):
            url = pattern.sub(langflow_url.rstrip("/"), url)
            logger.debug(f"Patched URL: {url}")
        return url

    async def patch_mcp_server_url(self, server_name: str) -> bool:
        """Patch a single MCP server to update the Langflow URL and convert to streamable HTTP if applicable.

        Only updates the URL (replacing localhost references with the configured LANGFLOW_URL).
        If the server is in stdio mode and eligible, converts it to streamable HTTP mode.
        Headers are never modified.
        """
        try:
            current = await self.get_mcp_server(server_name)

            if self._is_convertible_to_streamable_http(current):
                # Convert stdio to streamable HTTP: extract URL from args, patch it
                args = current.get("args", [])
                url, headers = self._parse_stdio_args(args)
                if url:
                    payload = {"url": self._patch_url_with_langflow_url(url), "headers": headers}
                    mode = "streamable_http (converted)"
                    logger.info(
                        "Converting MCP server to streamable HTTP",
                        server_name=server_name,
                    )
                else:
                    # Cannot extract URL — leave as-is
                    logger.debug(
                        "Could not extract URL from stdio args, skipping",
                        server_name=server_name,
                    )
                    return True
            elif self._is_streamable_http_mode(current):
                # Already streamable HTTP: only patch the URL, keep headers untouched
                url = current.get("url")
                patched_url = self._patch_url_with_langflow_url(url)
                if patched_url == url:
                    # URL unchanged — nothing to do
                    logger.debug(
                        "MCP server URL unchanged, skipping patch",
                        server_name=server_name,
                    )
                    return True
                payload = {"url": patched_url}
                mode = "streamable_http"
            else:
                # Stdio mode, not convertible — patch URL in args if present
                args = current.get("args", [])
                patched_args = list(args)
                url_patched = False
                for i, arg in enumerate(patched_args):
                    if isinstance(arg, str) and (
                        arg.startswith("http://") or arg.startswith("https://")
                    ):
                        new_url = self._patch_url_with_langflow_url(arg)
                        if new_url != arg:
                            patched_args[i] = new_url
                            url_patched = True
                if not url_patched:
                    logger.debug(
                        "No URL to patch in stdio args, skipping",
                        server_name=server_name,
                    )
                    return True
                command = current.get("command")
                payload = {"command": command, "args": patched_args}
                mode = "stdio"

            response = await clients.langflow_request(
                method="PATCH",
                endpoint=f"/api/v2/mcp/servers/{server_name}",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Patched MCP server URL",
                    server_name=server_name,
                    mode=mode,
                )
                return True
            else:
                logger.warning(
                    "Failed to patch MCP server URL",
                    server_name=server_name,
                    mode=mode,
                    status_code=response.status_code,
                    body=response.text,
                )
                return False
        except Exception as e:
            logger.error(
                "Exception while patching MCP server URL",
                server_name=server_name,
                error=str(e),
            )
            return False

    async def update_all_mcp_server_urls(self) -> Dict[str, Any]:
        """Fetch all MCP servers and update their URLs (replacing localhost with LANGFLOW_URL).

        Also converts eligible stdio servers to streamable HTTP mode.
        Returns a summary dict with counts.
        """
        servers = await self.list_mcp_servers()
        if not servers:
            return {"updated": 0, "failed": 0, "total": 0}

        updated = 0
        failed = 0
        for server in servers:
            name = server.get("name") or server.get("server") or server.get("id")
            if not name:
                continue
            ok = await self.patch_mcp_server_url(name)
            if ok:
                updated += 1
            else:
                failed += 1

        summary = {"updated": updated, "failed": failed, "total": len(servers)}
        if failed == 0:
            logger.info("MCP servers URL update completed", **summary)
        else:
            logger.warning("MCP servers URL update had failures", **summary)
        return summary
