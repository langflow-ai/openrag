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

    def _upsert_jwt_header_in_args(self, args: List[str], jwt_token: str) -> List[str]:
        """Ensure args contains a header triplet for X-Langflow-Global-Var-JWT with the provided JWT.

        Args are expected in the pattern: [..., "--headers", key, value, ...].
        If the header exists, update its value; otherwise append the triplet at the end.
        """
        if not isinstance(args, list):
            return [
                "mcp-proxy",
                "--headers",
                "X-Langflow-Global-Var-JWT",
                jwt_token,
            ]

        updated_args = list(args)
        i = 0
        found_index = -1
        while i < len(updated_args):
            token = updated_args[i]
            if token == "--headers" and i + 2 < len(updated_args):
                header_key = updated_args[i + 1]
                if (
                    isinstance(header_key, str)
                    and header_key.lower() == "x-langflow-global-var-jwt".lower()
                ):
                    found_index = i
                    break
                i += 3
                continue
            i += 1

        if found_index >= 0:
            # Replace existing value at found_index + 2
            if found_index + 2 < len(updated_args):
                updated_args[found_index + 2] = jwt_token
            else:
                # Malformed existing header triplet; make sure to append a value
                updated_args.append(jwt_token)
        else:
            updated_args.extend(
                [
                    "--headers",
                    "X-Langflow-Global-Var-JWT",
                    jwt_token,
                ]
            )

        return updated_args

    def _upsert_global_var_headers_in_args(
        self, args: List[str], global_vars: Dict[str, str]
    ) -> List[str]:
        """Ensure args contains header triplets for X-Langflow-Global-Var-{key} with the provided global variables.

        Args are expected in the pattern: [..., "--headers", key, value, ...].
        If a header exists, update its value; otherwise append the triplet at the end.
        """
        if not isinstance(args, list):
            updated_args = ["mcp-proxy"]
        else:
            updated_args = list(args)

        for var_key, var_value in global_vars.items():
            header_name = f"X-Langflow-Global-Var-{var_key}"

            i = 0
            found_index = -1
            while i < len(updated_args):
                token = updated_args[i]
                if token == "--headers" and i + 2 < len(updated_args):
                    header_key = updated_args[i + 1]
                    if (
                        isinstance(header_key, str)
                        and header_key.lower() == header_name.lower()
                    ):
                        found_index = i
                        break
                    i += 3
                    continue
                i += 1

            if found_index >= 0:
                # Replace existing value at found_index + 2
                if found_index + 2 < len(updated_args):
                    updated_args[found_index + 2] = var_value
                else:
                    # Malformed existing header triplet; make sure to append a value
                    updated_args.append(var_value)
            else:
                updated_args.extend(
                    [
                        "--headers",
                        header_name,
                        var_value,
                    ]
                )

        return updated_args

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
        - Args contain a URL ending with /mcp or /streamable
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
            if not (arg.startswith("http://") or arg.startswith("https://")):
                continue
            # Check URL path endings
            if arg.rstrip("/").endswith("/mcp") or arg.rstrip("/").endswith(
                "/streamable"
            ):
                return True

        return False

    def _is_streamable_http_mode(self, server_config: Dict[str, Any]) -> bool:
        """Check if server is in streamable HTTP mode (has url field)."""
        return bool(server_config.get("url"))

    def _upsert_global_var_headers_in_dict(
        self, headers: Dict[str, str] | None, global_vars: Dict[str, str]
    ) -> Dict[str, str]:
        """Upsert global var headers into a headers dictionary (for streamable HTTP mode).

        Creates X-Langflow-Global-Var-{key} headers in the dictionary.
        Case-insensitive matching for existing headers.
        """
        if headers is None:
            headers = {}
        else:
            headers = dict(headers)

        for var_key, var_value in global_vars.items():
            header_name = f"X-Langflow-Global-Var-{var_key}"

            # Find existing header with case-insensitive match
            existing_key = None
            for key in headers:
                if key.lower() == header_name.lower():
                    existing_key = key
                    break

            if existing_key:
                headers[existing_key] = var_value
            else:
                headers[header_name] = var_value

        return headers

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

    async def patch_mcp_server_args_with_global_vars(
        self, server_name: str, global_vars: Dict[str, Any]
    ) -> bool:
        """Patch a single MCP server to include/update multiple X-Langflow-Global-Var-* headers.

        Supports both stdio mode (command/args) and streamable HTTP mode (url/headers).
        Only non-empty values are applied. Keys are uppercased to match existing conventions (e.g., JWT).
        """
        try:
            if not isinstance(global_vars, dict) or not global_vars:
                return True  # Nothing to do

            # Sanitize and normalize keys/values
            sanitized: Dict[str, str] = {}
            for k, v in global_vars.items():
                if v is None:
                    continue
                v_str = str(v).strip()
                if not v_str:
                    continue
                sanitized[k.upper()] = v_str

            if not sanitized:
                return True

            # Fetch server config once
            current = await self.get_mcp_server(server_name)

            # In IBM Auth mode, convert stdio to streamable HTTP inline if eligible
            from config.settings import IBM_AUTH_ENABLED

            if IBM_AUTH_ENABLED and self._is_convertible_to_streamable_http(current):
                args = current.get("args", [])
                url, headers = self._parse_stdio_args(args)
                if url:
                    # Build streamable HTTP payload with converted config + new headers
                    updated_headers = self._upsert_global_var_headers_in_dict(
                        headers, sanitized
                    )
                    payload = {"url": self._patch_url_with_langflow_url(url), "headers": updated_headers}
                    mode = "streamable_http"
                    logger.info(
                        "Converting MCP server to streamable HTTP with headers",
                        server_name=server_name,
                    )
                else:
                    # Fallback to stdio mode if URL extraction failed
                    command = current.get("command")
                    updated_args = self._upsert_global_var_headers_in_args(
                        args, sanitized
                    )
                    payload = {"command": command, "args": updated_args}
                    mode = "stdio"
            elif self._is_streamable_http_mode(current):
                # Already in streamable HTTP mode: update headers dictionary
                url = current.get("url")
                headers = current.get("headers", {})
                updated_headers = self._upsert_global_var_headers_in_dict(
                    headers, sanitized
                )
                payload = {"url": url, "headers": updated_headers}
                mode = "streamable_http"
            else:
                # Stdio mode: update args list
                command = current.get("command")
                args = current.get("args", [])
                updated_args = self._upsert_global_var_headers_in_args(args, sanitized)
                payload = {"command": command, "args": updated_args}
                mode = "stdio"

            response = await clients.langflow_request(
                method="PATCH",
                endpoint=f"/api/v2/mcp/servers/{server_name}",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Patched MCP server with global-var headers",
                    server_name=server_name,
                    mode=mode,
                    applied_keys=list(sanitized.keys()),
                )
                return True
            else:
                logger.warning(
                    "Failed to patch MCP server with global vars",
                    server_name=server_name,
                    mode=mode,
                    status_code=response.status_code,
                    body=response.text,
                )
                return False
        except Exception as e:
            logger.error(
                "Exception while patching MCP server with global vars",
                server_name=server_name,
                error=str(e),
            )
            return False

    async def update_mcp_servers_with_global_vars(
        self, global_vars: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Fetch all MCP servers and ensure each includes provided global-var headers in args.

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
            ok = await self.patch_mcp_server_args_with_global_vars(name, global_vars)
            if ok:
                updated += 1
            else:
                failed += 1

        summary = {"updated": updated, "failed": failed, "total": len(servers)}
        if failed == 0:
            logger.info("MCP servers updated with global-var headers", **summary)
        else:
            logger.warning("MCP servers update (global vars) had failures", **summary)
        return summary

    async def patch_mcp_server_args_with_jwt(
        self, server_name: str, jwt_token: str
    ) -> bool:
        """Patch a single MCP server to include/update the JWT header.

        Supports both stdio mode (command/args) and streamable HTTP mode (url/headers).
        """
        try:
            current = await self.get_mcp_server(server_name)

            # Detect server mode and build appropriate payload
            if self._is_streamable_http_mode(current):
                # Streamable HTTP mode: update headers dictionary
                url = current.get("url")
                headers = current.get("headers", {})
                updated_headers = self._upsert_global_var_headers_in_dict(
                    headers, {"JWT": jwt_token}
                )
                payload = {"url": url, "headers": updated_headers}
                mode = "streamable_http"
            else:
                # Stdio mode: update args list
                command = current.get("command")
                args = current.get("args", [])
                updated_args = self._upsert_jwt_header_in_args(args, jwt_token)
                payload = {"command": command, "args": updated_args}
                mode = "stdio"

            response = await clients.langflow_request(
                method="PATCH",
                endpoint=f"/api/v2/mcp/servers/{server_name}",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Patched MCP server with JWT header",
                    server_name=server_name,
                    mode=mode,
                )
                return True
            else:
                logger.warning(
                    "Failed to patch MCP server",
                    server_name=server_name,
                    mode=mode,
                    status_code=response.status_code,
                    body=response.text,
                )
                return False
        except Exception as e:
            logger.error(
                "Exception while patching MCP server",
                server_name=server_name,
                error=str(e),
            )
            return False

    async def update_mcp_servers_with_jwt(self, jwt_token: str) -> Dict[str, Any]:
        """Fetch all MCP servers and ensure each includes the JWT header in args.

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
            ok = await self.patch_mcp_server_args_with_jwt(name, jwt_token)
            if ok:
                updated += 1
            else:
                failed += 1

        summary = {"updated": updated, "failed": failed, "total": len(servers)}
        if failed == 0:
            logger.info("MCP servers updated with JWT header", **summary)
        else:
            logger.warning("MCP servers update had failures", **summary)
        return summary

    async def convert_server_to_streamable_http(self, server_name: str) -> bool:
        """Convert a stdio MCP server to streamable HTTP format.

        1. Fetch current server config
        2. Check if convertible (stdio with URL ending in /mcp or /streamable)
        3. Extract URL and headers from args
        4. PATCH server with {url, headers} format
        """
        try:
            current = await self.get_mcp_server(server_name)

            if not self._is_convertible_to_streamable_http(current):
                logger.debug(
                    "Server not convertible to streamable HTTP",
                    server_name=server_name,
                )
                return False

            args = current.get("args", [])
            url, headers = self._parse_stdio_args(args)

            if not url:
                logger.warning(
                    "Could not extract URL from stdio args",
                    server_name=server_name,
                    args=args,
                )
                return False

            payload = {"url": url, "headers": headers}
            response = await clients.langflow_request(
                method="PATCH",
                endpoint=f"/api/v2/mcp/servers/{server_name}",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Converted MCP server to streamable HTTP",
                    server_name=server_name,
                    url=url,
                    headers_count=len(headers),
                )
                return True
            else:
                logger.warning(
                    "Failed to convert MCP server to streamable HTTP",
                    server_name=server_name,
                    status_code=response.status_code,
                    body=response.text,
                )
                return False
        except Exception as e:
            logger.error(
                "Exception while converting MCP server to streamable HTTP",
                server_name=server_name,
                error=str(e),
            )
            return False

    async def convert_all_servers_to_streamable_http(self) -> Dict[str, Any]:
        """Convert all eligible stdio servers to streamable HTTP.

        A server is eligible if:
        - It has a 'command' field (stdio mode)
        - First arg is a URL ending with /mcp or /streamable

        Returns summary: {converted, skipped, failed, total}
        """
        servers = await self.list_mcp_servers()
        if not servers:
            return {"converted": 0, "skipped": 0, "failed": 0, "total": 0}

        converted = 0
        skipped = 0
        failed = 0

        for server in servers:
            name = server.get("name") or server.get("server") or server.get("id")
            if not name:
                continue

            if not self._is_convertible_to_streamable_http(server):
                skipped += 1
                continue

            ok = await self.convert_server_to_streamable_http(name)
            if ok:
                converted += 1
            else:
                failed += 1

        summary = {
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "total": len(servers),
        }
        if failed == 0:
            logger.info(
                "MCP servers conversion to streamable HTTP completed", **summary
            )
        else:
            logger.warning("MCP servers conversion had failures", **summary)
        return summary
