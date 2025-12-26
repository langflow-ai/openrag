# """Document tools for OpenRAG MCP server."""

# import logging
# from pathlib import Path

# from mcp.server import Server
# from mcp.types import TextContent, Tool

# from openrag_sdk import (
#     AuthenticationError,
#     NotFoundError,
#     OpenRAGError,
#     RateLimitError,
#     ServerError,
#     ValidationError,
# )

# from openrag_mcp.config import get_client, get_openrag_client

# logger = logging.getLogger("openrag-mcp.documents")


# def register_document_tools(server: Server) -> None:
#     """Register document-related tools with the MCP server."""

#     @server.list_tools()
#     async def list_document_tools() -> list[Tool]:
#         """List document tools."""
#         return [
#             Tool(
#                 name="openrag_ingest_file",
#                 description=(
#                     "Ingest a local file into the OpenRAG knowledge base. "
#                     "Supported formats: PDF, DOCX, TXT, MD, HTML, and more."
#                 ),
#                 inputSchema={
#                     "type": "object",
#                     "properties": {
#                         "file_path": {
#                             "type": "string",
#                             "description": "Absolute path to the file to ingest",
#                         },
#                     },
#                     "required": ["file_path"],
#                 },
#             ),
#             Tool(
#                 name="openrag_ingest_url",
#                 description=(
#                     "Ingest content from a URL into the OpenRAG knowledge base. "
#                     "The URL content will be fetched, processed, and stored."
#                 ),
#                 inputSchema={
#                     "type": "object",
#                     "properties": {
#                         "url": {
#                             "type": "string",
#                             "description": "The URL to fetch and ingest",
#                         },
#                     },
#                     "required": ["url"],
#                 },
#             ),
#             Tool(
#                 name="openrag_list_documents",
#                 description="List documents in the OpenRAG knowledge base.",
#                 inputSchema={
#                     "type": "object",
#                     "properties": {
#                         "limit": {
#                             "type": "integer",
#                             "description": "Maximum number of documents to return (default: 50)",
#                             "default": 50,
#                         },
#                     },
#                     "required": [],
#                 },
#             ),
#             Tool(
#                 name="openrag_delete_document",
#                 description="Delete a document from the OpenRAG knowledge base.",
#                 inputSchema={
#                     "type": "object",
#                     "properties": {
#                         "filename": {
#                             "type": "string",
#                             "description": "Name of the file to delete",
#                         },
#                     },
#                     "required": ["filename"],
#                 },
#             ),
#         ]

#     @server.call_tool()
#     async def call_document_tool(name: str, arguments: dict) -> list[TextContent]:
#         """Handle document tool calls."""
#         if name == "openrag_ingest_file":
#             return await _ingest_file(arguments)
#         elif name == "openrag_ingest_url":
#             return await _ingest_url(arguments)
#         elif name == "openrag_list_documents":
#             return await _list_documents(arguments)
#         elif name == "openrag_delete_document":
#             return await _delete_document(arguments)
#         return []


# async def _ingest_file(arguments: dict) -> list[TextContent]:
#     """Ingest a local file into OpenRAG using the SDK."""
#     file_path = arguments.get("file_path", "")

#     if not file_path:
#         return [TextContent(type="text", text="Error: file_path is required")]

#     path = Path(file_path)

#     if not path.exists():
#         return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

#     if not path.is_file():
#         return [TextContent(type="text", text=f"Error: Path is not a file: {file_path}")]

#     try:
#         client = get_openrag_client()
#         # Use wait=False to return immediately with task_id
#         response = await client.documents.ingest(file_path=path, wait=False)

#         result = f"Successfully queued '{response.filename or path.name}' for ingestion."
#         if response.task_id:
#             result += f"\nTask ID: {response.task_id}"

#         return [TextContent(type="text", text=result)]

#     except AuthenticationError as e:
#         logger.error(f"Authentication error: {e.message}")
#         return [TextContent(type="text", text=f"Authentication error: {e.message}")]
#     except ValidationError as e:
#         logger.error(f"Validation error: {e.message}")
#         return [TextContent(type="text", text=f"Invalid request: {e.message}")]
#     except RateLimitError as e:
#         logger.error(f"Rate limit error: {e.message}")
#         return [TextContent(type="text", text=f"Rate limited: {e.message}")]
#     except ServerError as e:
#         logger.error(f"Server error: {e.message}")
#         return [TextContent(type="text", text=f"Server error: {e.message}")]
#     except OpenRAGError as e:
#         logger.error(f"OpenRAG error: {e.message}")
#         return [TextContent(type="text", text=f"Error: {e.message}")]
#     except Exception as e:
#         logger.error(f"Ingest file error: {e}")
#         return [TextContent(type="text", text=f"Error ingesting file: {str(e)}")]


# async def _ingest_url(arguments: dict) -> list[TextContent]:
#     """Ingest content from a URL into OpenRAG.

#     Note: This uses the SDK's chat to trigger URL ingestion via the agent.
#     """
#     url = arguments.get("url", "")

#     if not url:
#         return [TextContent(type="text", text="Error: url is required")]

#     if not url.startswith(("http://", "https://")):
#         return [TextContent(type="text", text="Error: url must start with http:// or https://")]

#     try:
#         # Use chat with a special prompt to trigger URL ingestion via the agent
#         client = get_openrag_client()
#         response = await client.chat.create(
#             message=f"Please ingest the content from this URL into the knowledge base: {url}",
#         )

#         return [TextContent(type="text", text=f"URL ingestion requested.\n\n{response.response}")]

#     except AuthenticationError as e:
#         logger.error(f"Authentication error: {e.message}")
#         return [TextContent(type="text", text=f"Authentication error: {e.message}")]
#     except ServerError as e:
#         logger.error(f"Server error: {e.message}")
#         return [TextContent(type="text", text=f"Server error: {e.message}")]
#     except OpenRAGError as e:
#         logger.error(f"OpenRAG error: {e.message}")
#         return [TextContent(type="text", text=f"Error: {e.message}")]
#     except Exception as e:
#         logger.error(f"Ingest URL error: {e}")
#         return [TextContent(type="text", text=f"Error ingesting URL: {str(e)}")]


# async def _list_documents(arguments: dict) -> list[TextContent]:
#     """List documents in the knowledge base.

#     Note: This uses direct HTTP calls as the SDK doesn't yet support listing documents.
#     """
#     limit = arguments.get("limit", 50)

#     try:
#         async with get_client() as client:
#             response = await client.get("/api/v1/documents", params={"limit": limit})
#             response.raise_for_status()
#             data = response.json()

#             documents = data.get("documents", [])

#             if not documents:
#                 return [TextContent(type="text", text="No documents found in the knowledge base.")]

#             output_parts = [f"Found {len(documents)} document(s):\n"]

#             for doc in documents:
#                 filename = doc.get("filename", "Unknown")
#                 chunks = doc.get("chunk_count", 0)
#                 created = doc.get("created_at", "")

#                 output_parts.append(f"\n- **{filename}** ({chunks} chunks)")
#                 if created:
#                     output_parts.append(f" - Added: {created[:10]}")

#             return [TextContent(type="text", text="".join(output_parts))]

#     except Exception as e:
#         logger.error(f"List documents error: {e}")
#         return [TextContent(type="text", text=f"Error listing documents: {str(e)}")]


# async def _delete_document(arguments: dict) -> list[TextContent]:
#     """Delete a document from the knowledge base using the SDK."""
#     filename = arguments.get("filename", "")

#     if not filename:
#         return [TextContent(type="text", text="Error: filename is required")]

#     try:
#         client = get_openrag_client()
#         response = await client.documents.delete(filename)

#         return [TextContent(
#             type="text",
#             text=f"Successfully deleted '{filename}' ({response.deleted_chunks} chunks removed).",
#         )]

#     except NotFoundError as e:
#         logger.error(f"Document not found: {e.message}")
#         return [TextContent(type="text", text=f"Document not found: {e.message}")]
#     except AuthenticationError as e:
#         logger.error(f"Authentication error: {e.message}")
#         return [TextContent(type="text", text=f"Authentication error: {e.message}")]
#     except ServerError as e:
#         logger.error(f"Server error: {e.message}")
#         return [TextContent(type="text", text=f"Server error: {e.message}")]
#     except OpenRAGError as e:
#         logger.error(f"OpenRAG error: {e.message}")
#         return [TextContent(type="text", text=f"Error: {e.message}")]
#     except Exception as e:
#         logger.error(f"Delete document error: {e}")
#         return [TextContent(type="text", text=f"Error deleting document: {str(e)}")]
