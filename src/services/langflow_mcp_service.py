from typing import List, Dict, Any

from config.settings import clients
from utils.logging_config import get_logger


logger = get_logger(__name__)


class LangflowMCPService:
    async def list_mcp_servers(self) -> List[Dict[str, Any]]:
        """Fetch list of MCP servers from Langflow (v2 API)."""
        try:
            response = await clients.langflow_request(
                method="GET",
                endpoint="/api/v2/mcp/servers",
                params={"action_count": "false"},
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            logger.warning("Unexpected response format for MCP servers list", data_type=type(data).__name__)
            return []
        except Exception as e:
            logger.error("Failed to list MCP servers", error=str(e))
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
                if isinstance(header_key, str) and header_key.lower() == "x-langflow-global-var-jwt".lower():
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
            updated_args.extend([
                "--headers",
                "X-Langflow-Global-Var-JWT",
                jwt_token,
            ])

        return updated_args

    async def patch_mcp_server_args_with_jwt(self, server_name: str, jwt_token: str) -> bool:
        """Patch a single MCP server to include/update the JWT header in args."""
        try:
            current = await self.get_mcp_server(server_name)
            command = current.get("command")
            args = current.get("args", [])
            updated_args = self._upsert_jwt_header_in_args(args, jwt_token)

            payload = {"command": command, "args": updated_args}
            response = await clients.langflow_request(
                method="PATCH",
                endpoint=f"/api/v2/mcp/servers/{server_name}",
                json=payload,
            )
            if response.status_code in (200, 201):
                logger.info(
                    "Patched MCP server with JWT header",
                    server_name=server_name,
                    args_len=len(updated_args),
                )
                return True
            else:
                logger.warning(
                    "Failed to patch MCP server",
                    server_name=server_name,
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


