"""Asynchronous helper for building widget instruction prompts via MCP."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import List, Optional, Tuple

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)

_CACHE_TTL_SECONDS = 30.0
_cache_lock = asyncio.Lock()
_cached_block: Optional[str] = None
_cache_expiry: float = 0.0


def _parse_mcp_payload(body: str, content_type: str) -> Optional[dict]:
    if "text/event-stream" in content_type:
        last_data = None
        for block in body.split("\n\n"):
            for line in block.split("\n"):
                if line.startswith("data:"):
                    last_data = line[5:].strip()
        if not last_data:
            return None
        try:
            return json.loads(last_data)
        except json.JSONDecodeError:
            return None

    if not body:
        return None

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


async def _fetch_widget_resources() -> List[Tuple[str, Optional[str], Optional[str]]]:
    host = os.getenv("OPENRAG_BACKEND_HOST", "localhost")
    port = os.getenv("OPENRAG_BACKEND_PORT", "8000")
    ssl_enabled = os.getenv("OPENRAG_BACKEND_SSL", "false").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }
    protocol = "https" if ssl_enabled else "http"
    base_url = f"{protocol}://{host}:{port}"
    url = f"{base_url}/mcp/widgets/mcp/messages"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": "resources-list",
        "method": "resources/list",
        "params": {},
    }

    timeout = httpx.Timeout(3.0, read=3.0, write=3.0, pool=3.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.debug("Widget MCP request failed", error=str(exc))
        return []

    if response.status_code != 200:
        logger.debug(
            "Widget MCP request returned non-200",
            status=response.status_code,
            body_preview=response.text[:200],
        )
        return []

    data = _parse_mcp_payload(response.text, response.headers.get("content-type", ""))
    if not data:
        return []

    resources = data.get("result", {}).get("resources", [])
    items: List[Tuple[str, Optional[str], Optional[str]]] = []
    for resource in resources:
        uri = resource.get("uri")
        if not uri:
            continue
        name = resource.get("name") or resource.get("title")
        description = resource.get("description")
        items.append((uri, name, description))
    return items


def _build_instruction_block(resources: List[Tuple[str, Optional[str], Optional[str]]]) -> str:
    if not resources:
        return ""

    lines = []
    for uri, name, description in resources:
        parts = []
        if name:
            parts.append(f"**{name}**")
        parts.append(f"`{uri}`")
        if description:
            parts.append(f"- {description}")
        lines.append(" ".join(parts))

    example_uri = resources[0][0]
    block = "You are able to display the following list of UI widgets:\n\n"
    block += "\n".join(lines)
    block += (
        "\n\nTo display a widget, simply return the widget URI wrapped in triple backticks, for example:\n\n```"
        f"\n{example_uri}\n```"
    )
    return block


async def get_widget_instruction_block(force_refresh: bool = False) -> str:
    global _cached_block, _cache_expiry

    async with _cache_lock:
        if not force_refresh and _cached_block and time.time() < _cache_expiry:
            return _cached_block

    resources = await _fetch_widget_resources()
    block = _build_instruction_block(resources)

    async with _cache_lock:
        _cached_block = block
        _cache_expiry = time.time() + _CACHE_TTL_SECONDS

    return block
