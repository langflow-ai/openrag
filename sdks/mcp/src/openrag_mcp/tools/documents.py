"""Document tools for OpenRAG MCP server."""

import logging
import os
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from openrag_mcp.config import get_client

logger = logging.getLogger("openrag-mcp.documents")


def register_document_tools(server: Server) -> None:
    """Register document-related tools with the MCP server."""

    @server.list_tools()
    async def list_document_tools() -> list[Tool]:
        """List document tools."""
        return [
            Tool(
                name="openrag_ingest_file",
                description=(
                    "Ingest a local file into the OpenRAG knowledge base. "
                    "Supported formats: PDF, DOCX, TXT, MD, HTML, and more."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Absolute path to the file to ingest",
                        },
                    },
                    "required": ["file_path"],
                },
            ),
            Tool(
                name="openrag_ingest_url",
                description=(
                    "Ingest content from a URL into the OpenRAG knowledge base. "
                    "The URL content will be fetched, processed, and stored."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch and ingest",
                        },
                    },
                    "required": ["url"],
                },
            ),
            Tool(
                name="openrag_list_documents",
                description="List documents in the OpenRAG knowledge base.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of documents to return (default: 50)",
                            "default": 50,
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="openrag_delete_document",
                description="Delete a document from the OpenRAG knowledge base.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Name of the file to delete",
                        },
                    },
                    "required": ["filename"],
                },
            ),
        ]

    @server.call_tool()
    async def call_document_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle document tool calls."""
        if name == "openrag_ingest_file":
            return await _ingest_file(arguments)
        elif name == "openrag_ingest_url":
            return await _ingest_url(arguments)
        elif name == "openrag_list_documents":
            return await _list_documents(arguments)
        elif name == "openrag_delete_document":
            return await _delete_document(arguments)
        return []


async def _ingest_file(arguments: dict) -> list[TextContent]:
    """Ingest a local file into OpenRAG."""
    file_path = arguments.get("file_path", "")

    if not file_path:
        return [TextContent(type="text", text="Error: file_path is required")]

    path = Path(file_path)

    if not path.exists():
        return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

    if not path.is_file():
        return [TextContent(type="text", text=f"Error: Path is not a file: {file_path}")]

    try:
        async with get_client() as client:
            # Read file and upload
            with open(path, "rb") as f:
                files = {"file": (path.name, f)}
                # Remove Content-Type header for multipart upload
                headers = dict(client.headers)
                headers.pop("Content-Type", None)

                response = await client.post(
                    "/api/v1/documents/ingest",
                    files=files,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            task_id = data.get("task_id")
            filename = data.get("filename", path.name)

            result = f"Successfully queued '{filename}' for ingestion."
            if task_id:
                result += f"\nTask ID: {task_id}"

            return [TextContent(type="text", text=result)]

    except Exception as e:
        logger.error(f"Ingest file error: {e}")
        return [TextContent(type="text", text=f"Error ingesting file: {str(e)}")]


async def _ingest_url(arguments: dict) -> list[TextContent]:
    """Ingest content from a URL into OpenRAG."""
    url = arguments.get("url", "")

    if not url:
        return [TextContent(type="text", text="Error: url is required")]

    if not url.startswith(("http://", "https://")):
        return [TextContent(type="text", text="Error: url must start with http:// or https://")]

    try:
        # Use chat with a special prompt to trigger URL ingestion via the agent
        async with get_client() as client:
            payload = {
                "message": f"Please ingest the content from this URL into the knowledge base: {url}",
                "stream": False,
            }

            response = await client.post("/api/v1/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            result_text = data.get("response", "")
            return [TextContent(type="text", text=f"URL ingestion requested.\n\n{result_text}")]

    except Exception as e:
        logger.error(f"Ingest URL error: {e}")
        return [TextContent(type="text", text=f"Error ingesting URL: {str(e)}")]


async def _list_documents(arguments: dict) -> list[TextContent]:
    """List documents in the knowledge base."""
    limit = arguments.get("limit", 50)

    try:
        async with get_client() as client:
            response = await client.get("/api/v1/documents", params={"limit": limit})
            response.raise_for_status()
            data = response.json()

            documents = data.get("documents", [])

            if not documents:
                return [TextContent(type="text", text="No documents found in the knowledge base.")]

            output_parts = [f"Found {len(documents)} document(s):\n"]

            for doc in documents:
                filename = doc.get("filename", "Unknown")
                chunks = doc.get("chunk_count", 0)
                created = doc.get("created_at", "")

                output_parts.append(f"\n- **{filename}** ({chunks} chunks)")
                if created:
                    output_parts.append(f" - Added: {created[:10]}")

            return [TextContent(type="text", text="".join(output_parts))]

    except Exception as e:
        logger.error(f"List documents error: {e}")
        return [TextContent(type="text", text=f"Error listing documents: {str(e)}")]


async def _delete_document(arguments: dict) -> list[TextContent]:
    """Delete a document from the knowledge base."""
    filename = arguments.get("filename", "")

    if not filename:
        return [TextContent(type="text", text="Error: filename is required")]

    try:
        async with get_client() as client:
            response = await client.request(
                "DELETE",
                "/api/v1/documents",
                json={"filename": filename},
            )
            response.raise_for_status()
            data = response.json()

            deleted_count = data.get("deleted_count", 0)
            return [TextContent(
                type="text",
                text=f"Successfully deleted '{filename}' ({deleted_count} chunks removed).",
            )]

    except Exception as e:
        logger.error(f"Delete document error: {e}")
        return [TextContent(type="text", text=f"Error deleting document: {str(e)}")]

