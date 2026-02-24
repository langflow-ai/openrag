"""Document tools for OpenRAG MCP server."""

import logging
from pathlib import Path

from mcp.types import TextContent, Tool

from openrag_sdk import (
    AuthenticationError,
    NotFoundError,
    OpenRAGError,
    RateLimitError,
    ServerError,
    ValidationError,
)

from openrag_mcp.config import get_openrag_client
from openrag_mcp.tools.registry import register_tool

logger = logging.getLogger("openrag-mcp.documents")


# ============================================================================
# Tool: openrag_ingest_file
# ============================================================================

INGEST_FILE_TOOL = Tool(
    name="openrag_ingest_file",
    description=(
        "Ingest a local file into the OpenRAG knowledge base. "
        "Supported formats: PDF, DOCX, TXT, MD, HTML, and more. "
        "By default waits for ingestion to complete. Set wait=false to return immediately."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to ingest",
            },
            "wait": {
                "type": "boolean",
                "description": "Wait for ingestion to complete (default: true). Set to false to return immediately with task_id.",
                "default": True,
            },
        },
        "required": ["file_path"],
    },
)


async def handle_ingest_file(arguments: dict) -> list[TextContent]:
    """Handle openrag_ingest_file tool calls."""
    file_path = arguments.get("file_path", "")
    wait = arguments.get("wait", True)

    if not file_path:
        return [TextContent(type="text", text="Error: file_path is required")]

    path = Path(file_path)

    if not path.exists():
        return [TextContent(type="text", text=f"Error: File not found: {file_path}")]

    if not path.is_file():
        return [TextContent(type="text", text=f"Error: Path is not a file: {file_path}")]

    try:
        client = get_openrag_client()
        response = await client.documents.ingest(file_path=path, wait=wait)

        if wait:
            status = response.status
            successful = response.successful_files
            failed = response.failed_files

            if status == "completed":
                result = f"Successfully ingested '{path.name}'."
                result += f"\nStatus: {status}"
                result += f"\nSuccessful files: {successful}"
                if failed > 0:
                    result += f"\nFailed files: {failed}"
            else:
                result = f"Ingestion finished with status: {status}"
                result += f"\nSuccessful files: {successful}"
                result += f"\nFailed files: {failed}"
        else:
            result = f"Successfully queued '{response.filename or path.name}' for ingestion."
            if response.task_id:
                result += f"\nTask ID: {response.task_id}"
                result += "\n\nUse openrag_get_task_status or openrag_wait_for_task to check progress."

        return [TextContent(type="text", text=result)]

    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except ValidationError as e:
        logger.error(f"Validation error: {e.message}")
        return [TextContent(type="text", text=f"Invalid request: {e.message}")]
    except RateLimitError as e:
        logger.error(f"Rate limit error: {e.message}")
        return [TextContent(type="text", text=f"Rate limited: {e.message}")]
    except ServerError as e:
        logger.error(f"Server error: {e.message}")
        return [TextContent(type="text", text=f"Server error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except TimeoutError as e:
        logger.error(f"Timeout error: {e}")
        return [TextContent(type="text", text=f"Ingestion timed out: {str(e)}")]
    except Exception as e:
        logger.error(f"Ingest file error: {e}")
        return [TextContent(type="text", text=f"Error ingesting file: {str(e)}")]


# ============================================================================
# Tool: openrag_ingest_url
# ============================================================================

INGEST_URL_TOOL = Tool(
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
)


async def handle_ingest_url(arguments: dict) -> list[TextContent]:
    """Handle openrag_ingest_url tool calls."""
    url = arguments.get("url", "")

    if not url:
        return [TextContent(type="text", text="Error: url is required")]

    if not url.startswith(("http://", "https://")):
        return [TextContent(type="text", text="Error: url must start with http:// or https://")]

    try:
        client = get_openrag_client()
        response = await client.chat.create(
            message=f"Please ingest the content from this URL into the knowledge base: {url}",
        )

        return [TextContent(type="text", text=f"URL ingestion requested.\n\n{response.response}")]

    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except ServerError as e:
        logger.error(f"Server error: {e.message}")
        return [TextContent(type="text", text=f"Server error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except Exception as e:
        logger.error(f"Ingest URL error: {e}")
        return [TextContent(type="text", text=f"Error ingesting URL: {str(e)}")]


# ============================================================================
# Tool: openrag_get_task_status
# ============================================================================

GET_TASK_STATUS_TOOL = Tool(
    name="openrag_get_task_status",
    description=(
        "Check the status of an ingestion task. "
        "Use the task_id returned from openrag_ingest_file when wait=false."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task ID to check status for",
            },
        },
        "required": ["task_id"],
    },
)


async def handle_get_task_status(arguments: dict) -> list[TextContent]:
    """Handle openrag_get_task_status tool calls."""
    task_id = arguments.get("task_id", "")

    if not task_id:
        return [TextContent(type="text", text="Error: task_id is required")]

    try:
        client = get_openrag_client()
        status = await client.documents.get_task_status(task_id)

        output_parts = [f"**Task Status: {status.status}**"]
        output_parts.append(f"\nTask ID: {status.task_id}")
        output_parts.append(f"\nTotal files: {status.total_files}")
        output_parts.append(f"\nProcessed: {status.processed_files}")
        output_parts.append(f"\nSuccessful: {status.successful_files}")
        output_parts.append(f"\nFailed: {status.failed_files}")

        if status.files:
            output_parts.append("\n\n**File Details:**")
            for filename, file_status in status.files.items():
                output_parts.append(f"\n- {filename}: {file_status}")

        return [TextContent(type="text", text="".join(output_parts))]

    except NotFoundError as e:
        logger.error(f"Task not found: {e.message}")
        return [TextContent(type="text", text=f"Task not found: {e.message}")]
    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except Exception as e:
        logger.error(f"Get task status error: {e}")
        return [TextContent(type="text", text=f"Error getting task status: {str(e)}")]


# ============================================================================
# Tool: openrag_wait_for_task
# ============================================================================

WAIT_FOR_TASK_TOOL = Tool(
    name="openrag_wait_for_task",
    description=(
        "Wait for an ingestion task to complete. "
        "Polls the task status until it completes or fails."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task ID to wait for",
            },
            "timeout": {
                "type": "number",
                "description": "Maximum seconds to wait (default: 300)",
                "default": 300,
            },
        },
        "required": ["task_id"],
    },
)


async def handle_wait_for_task(arguments: dict) -> list[TextContent]:
    """Handle openrag_wait_for_task tool calls."""
    task_id = arguments.get("task_id", "")
    timeout = arguments.get("timeout", 300)

    if not task_id:
        return [TextContent(type="text", text="Error: task_id is required")]

    try:
        client = get_openrag_client()
        status = await client.documents.wait_for_task(task_id, timeout=timeout)

        output_parts = [f"**Task Completed: {status.status}**"]
        output_parts.append(f"\nTask ID: {status.task_id}")
        output_parts.append(f"\nTotal files: {status.total_files}")
        output_parts.append(f"\nSuccessful: {status.successful_files}")
        output_parts.append(f"\nFailed: {status.failed_files}")

        if status.files:
            output_parts.append("\n\n**File Details:**")
            for filename, file_status in status.files.items():
                output_parts.append(f"\n- {filename}: {file_status}")

        return [TextContent(type="text", text="".join(output_parts))]

    except TimeoutError as e:
        logger.error(f"Wait for task timeout: {e}")
        return [TextContent(type="text", text=f"Task did not complete within {timeout} seconds.")]
    except NotFoundError as e:
        logger.error(f"Task not found: {e.message}")
        return [TextContent(type="text", text=f"Task not found: {e.message}")]
    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except Exception as e:
        logger.error(f"Wait for task error: {e}")
        return [TextContent(type="text", text=f"Error waiting for task: {str(e)}")]


# ============================================================================
# Tool: openrag_delete_document
# ============================================================================

DELETE_DOCUMENT_TOOL = Tool(
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
)


async def handle_delete_document(arguments: dict) -> list[TextContent]:
    """Handle openrag_delete_document tool calls."""
    filename = arguments.get("filename", "")

    if not filename:
        return [TextContent(type="text", text="Error: filename is required")]

    try:
        client = get_openrag_client()
        response = await client.documents.delete(filename)

        if response.success:
            return [TextContent(
                type="text",
                text=f"Successfully deleted '{filename}' ({response.deleted_chunks} chunks removed).",
            )]
        else:
            return [TextContent(
                type="text",
                text=f"Failed to delete '{filename}'.",
            )]

    except NotFoundError as e:
        logger.error(f"Document not found: {e.message}")
        return [TextContent(type="text", text=f"Document not found: {e.message}")]
    except AuthenticationError as e:
        logger.error(f"Authentication error: {e.message}")
        return [TextContent(type="text", text=f"Authentication error: {e.message}")]
    except ServerError as e:
        logger.error(f"Server error: {e.message}")
        return [TextContent(type="text", text=f"Server error: {e.message}")]
    except OpenRAGError as e:
        logger.error(f"OpenRAG error: {e.message}")
        return [TextContent(type="text", text=f"Error: {e.message}")]
    except Exception as e:
        logger.error(f"Delete document error: {e}")
        return [TextContent(type="text", text=f"Error deleting document: {str(e)}")]


# ============================================================================
# Register all tools
# ============================================================================
#NOTE: Ingest Tools are disabled in OpenRAGMCP currently.