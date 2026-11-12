"""Native implementation of the shipped OpenRAG agent flow.

The flow JSON remains the product reference, but this module executes it
directly in Python. Pydantic AI owns the model/tool loop; OpenRAG remains the
single provider and embeddings authority through its OpenAI-compatible proxy.
"""

from __future__ import annotations

import ast
import asyncio
import copy
import ipaddress
import json
import math
import operator
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import httpx

# The onboarding banner is useful in a script, but noisy and misleading in a
# long-lived API process where the model intentionally uses OpenAI-compatible
# transport for OpenRAG's local gateway.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from config.config_manager import DEFAULT_SYSTEM_PROMPT
from config.settings import (
    OPENRAG_BACKEND_PORT,
    OPENRAG_BACKEND_ROUTER_ENABLE,
    OPENRAG_BACKEND_ROUTER_PORT,
    get_langflow_llm_base_url,
    get_openrag_config,
)
from services.langflow_llm_token_service import HOP_PURPOSE_CHAT, LangflowLlmTokenService
from services.native_chat_history_service import native_chat_history_service
from services.search_service import search_tool
from services.session_ownership_service import session_ownership_service
from utils.langflow_utils import fence_untrusted_text, strip_untrusted_fence_recursive
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_ITERATIONS = 15
MAX_CALCULATOR_INTEGER_BITS = 4_096
MAX_CALCULATOR_EXPONENT = 4_096
_BINARY_OPERATORS: dict[type[ast.operator], Callable[[int | float, int | float], int | float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[int | float], int | float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _calculate(expression: str) -> dict[str, Any]:
    """The Calculator component's arithmetic-only behaviour."""

    def validate_number(value: int | float) -> int | float:
        """Keep calculator operands within bounded CPU and memory limits."""
        if isinstance(value, int) and value.bit_length() > MAX_CALCULATOR_INTEGER_BITS:
            raise ValueError("Integer operands are too large")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Only finite numeric operands are supported")
        return value

    def validate_result(value: int | float) -> int | float:
        """Reject results that do not fit the calculator's numeric limits."""
        return validate_number(value)

    def validate_binary_operation(
        operation: ast.operator, left: int | float, right: int | float
    ) -> None:
        """Reject operations whose result would exceed the configured bounds."""
        validate_number(left)
        validate_number(right)
        if isinstance(operation, ast.Pow):
            if abs(right) > MAX_CALCULATOR_EXPONENT:
                raise ValueError("Exponent is too large")
            if isinstance(left, int) and isinstance(right, int) and right >= 0:
                # This bound is calculated from operand sizes, before ``pow``
                # can allocate an arbitrarily large integer.
                if left not in {-1, 0, 1} and left.bit_length() * right > MAX_CALCULATOR_INTEGER_BITS:
                    raise ValueError("Exponentiation result is too large")
            return
        if isinstance(left, int) and isinstance(right, int):
            if isinstance(operation, (ast.Add, ast.Sub)):
                result_bits = max(left.bit_length(), right.bit_length()) + 1
            elif isinstance(operation, ast.Mult):
                result_bits = left.bit_length() + right.bit_length()
            else:
                return
            if result_bits > MAX_CALCULATOR_INTEGER_BITS:
                raise ValueError("Calculation result is too large")

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return validate_number(node.value)
        if isinstance(node, ast.BinOp):
            binary_operation = _BINARY_OPERATORS.get(type(node.op))
            if binary_operation is not None:
                left, right = visit(node.left), visit(node.right)
                validate_binary_operation(node.op, left, right)
                return validate_result(binary_operation(left, right))
        if isinstance(node, ast.UnaryOp):
            unary_operation = _UNARY_OPERATORS.get(type(node.op))
            if unary_operation is not None:
                return validate_result(unary_operation(visit(node.operand)))
        raise ValueError("Only numeric arithmetic expressions are supported")

    try:
        return {"expression": expression, "result": visit(ast.parse(expression, mode="eval").body)}
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return {"error": str(exc)}


async def _read_public_url(value: str) -> dict[str, Any]:
    """Native counterpart to the flow's URL-ingestion tool, with SSRF protection."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {"error": "URL must be a bare http:// or https:// address"}
    try:
        addresses = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        )
        if any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            return {"error": "URLs resolving to private network addresses are not allowed"}
    except (OSError, ValueError):
        return {"error": "Unable to resolve the URL host"}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=20.0) as client:
            response = await client.get(value, headers={"User-Agent": "OpenRAG/1.0"})
            if response.is_redirect:
                return {"error": "Redirecting URLs are not supported"}
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"Could not read URL: {exc}"}
    extractor = _TextExtractor()
    extractor.feed(response.text)
    text = " ".join(extractor.parts)[:50_000]
    return {
        "url": str(response.url),
        "text": fence_untrusted_text(text),
    }


def _flow_prompt(prompt: str) -> str:
    """Match the shipped flow's Prompt Template component."""
    from auth_context import get_search_filters

    return (
        "This is Knowledge filter - use it as a context of what to search on the database, "
        f"unless it's empty: {json.dumps(get_search_filters() or {}, sort_keys=True)}\n\n"
        f"Chat input: {prompt}"
    )


def _tool_result(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"result": value}


def _native_llm_gateway_url() -> str:
    """Reach the same gateway as Langflow from the backend process itself.

    ``openrag-backend`` is the Docker service hostname used by Langflow. It is
    intentionally not resolvable when ``make backend`` runs on the host, so a
    native request replaces only that default with loopback. Explicit proxy
    URLs keep their configured host unchanged.
    """
    base_url = get_langflow_llm_base_url()
    parsed = urlsplit(base_url)
    if parsed.hostname != "openrag-backend":
        return base_url
    port = OPENRAG_BACKEND_ROUTER_PORT if OPENRAG_BACKEND_ROUTER_ENABLE else OPENRAG_BACKEND_PORT
    return urlunsplit((parsed.scheme or "http", f"127.0.0.1:{port}", parsed.path, parsed.query, ""))


class NativeChatAgent:
    """Run OpenRAG chat without starting Langflow."""

    async def run(
        self,
        *,
        prompt: str,
        user_id: str,
        previous_response_id: str | None,
        filter_id: str | None,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        conversation_id, history = await self._start(
            prompt, user_id, previous_response_id, filter_id
        )
        agent, model = self._agent(user_id)
        result = await agent.run(
            _flow_prompt(prompt),
            message_history=history,
            conversation_id=conversation_id,
            usage_limits=UsageLimits(request_limit=MAX_ITERATIONS),
        )
        response = str(result.output)
        self._require_response_text(response)
        sources = self._sources(result.new_messages())
        await self._save_completed_turn(conversation_id, user_id, response, [], result)
        logger.info(
            "[CHAT] Native OpenRAG chat completed",
            conversation_id=conversation_id,
            response_chars=len(response),
            sources=len(sources),
            llm_model=model,
            stream=False,
        )
        return response, conversation_id, sources

    async def stream(
        self,
        *,
        prompt: str,
        user_id: str,
        previous_response_id: str | None,
        filter_id: str | None,
    ) -> AsyncIterator[bytes]:
        conversation_id: str | None = previous_response_id
        chunks: list[dict[str, Any]] = []
        try:
            conversation_id, history = await self._start(
                prompt, user_id, previous_response_id, filter_id
            )
            agent, model = self._agent(user_id)
            events: asyncio.Queue[Any] = asyncio.Queue()

            async def collect_events(_context, event_stream) -> None:
                async for event in event_stream:
                    await events.put(event)

            task = asyncio.create_task(
                agent.run(
                    _flow_prompt(prompt),
                    message_history=history,
                    conversation_id=conversation_id,
                    usage_limits=UsageLimits(request_limit=MAX_ITERATIONS),
                    event_stream_handler=collect_events,
                )
            )
            call_inputs: dict[str, dict[str, Any]] = {}
            call_item_ids: dict[int, str] = {}
            while not task.done() or not events.empty():
                get_event = asyncio.create_task(events.get())
                done, _ = await asyncio.wait({task, get_event}, return_when=asyncio.FIRST_COMPLETED)
                if get_event in done:
                    for payload in self._stream_events(
                        get_event.result(), conversation_id, model, call_inputs, call_item_ids
                    ):
                        display_payload = copy.deepcopy(payload)
                        strip_untrusted_fence_recursive(display_payload)
                        chunks.append(display_payload)
                        yield self._event(display_payload)
                else:
                    get_event.cancel()
                    await asyncio.gather(get_event, return_exceptions=True)
            result = await task
            response = str(result.output)
            self._require_response_text(response)
            completed = self._completed_events(conversation_id, model, result)
            chunks.extend(completed)
            # The user has already received the answer tokens. A persistence
            # outage must not turn that completed answer into a failed chat.
            await self._save_completed_turn(conversation_id, user_id, response, chunks, result)
            for payload in completed:
                yield self._event(payload)
            logger.info(
                "[CHAT] Native OpenRAG stream completed",
                conversation_id=conversation_id,
                response_chars=len(response),
                sources=len(self._sources(result.new_messages())),
                stream_events=len(chunks),
            )
        except Exception as exc:
            message = self._public_error_message(exc)
            logger.warning(
                "[CHAT] Native OpenRAG chat failed",
                conversation_id=conversation_id,
                error_type=type(exc).__name__,
                error_message=message,
                error_detail=str(exc.__cause__ or exc),
            )
            if conversation_id:
                try:
                    await native_chat_history_service.append(
                        conversation_id, user_id, "assistant", content=message, error=True
                    )
                except Exception:
                    logger.exception("[CHAT] Failed to persist native chat error")
            error_payload: dict[str, Any] = {
                "status": "failed",
                "finish_reason": "error",
                "error": {"message": message},
            }
            if conversation_id:
                error_payload.update({"id": conversation_id, "response_id": conversation_id})
            yield self._event(error_payload)

    async def _start(
        self,
        prompt: str,
        user_id: str,
        previous_response_id: str | None,
        filter_id: str | None,
    ) -> tuple[str, list[Any]]:
        conversation_id = previous_response_id or str(uuid.uuid4())
        if previous_response_id:
            history = await native_chat_history_service.pydantic_history(conversation_id, user_id)
            if not history and not await native_chat_history_service.owns_conversation(
                conversation_id, user_id
            ):
                raise ValueError("Conversation was not found")
        else:
            await native_chat_history_service.start_conversation(
                conversation_id, user_id, filter_id
            )
            if not await session_ownership_service.claim_session(user_id, conversation_id):
                raise RuntimeError("Unable to establish native chat session ownership")
            history = []
        await native_chat_history_service.append(conversation_id, user_id, "user", content=prompt)
        config = get_openrag_config()
        logger.info(
            "[CHAT] Native OpenRAG agent started",
            conversation_id=conversation_id,
            continuing=bool(previous_response_id),
            history_messages=len(history),
            prompt_chars=len(prompt),
            llm_provider=getattr(config.agent, "llm_provider", None),
            llm_model=getattr(config.agent, "llm_model", None),
            embedding_provider=getattr(config.knowledge, "embedding_provider", None),
            embedding_model=getattr(config.knowledge, "embedding_model", None),
        )
        return conversation_id, history

    def _agent(self, user_id: str) -> tuple[Agent, str]:
        config = get_openrag_config()
        agent_config = getattr(config, "agent", None)
        model_name = getattr(agent_config, "llm_model", None)
        if not model_name:
            raise RuntimeError("No language model is configured for native chat")
        token = LangflowLlmTokenService().create_token(user_id=user_id, purpose=HOP_PURPOSE_CHAT)
        gateway_url = _native_llm_gateway_url()
        logger.info("[CHAT] Native OpenRAG LLM gateway", base_url=gateway_url, model=model_name)
        model = OpenAIChatModel(
            model_name,
            provider=OpenAIProvider(base_url=gateway_url, api_key=token),
        )

        async def search_documents(search_query: str) -> dict[str, Any]:
            """Search indexed OpenRAG documents for relevant content."""
            return self._fence_search_response(await search_tool(search_query))

        async def raw_search(search_query: str) -> dict[str, Any]:
            """Search indexed OpenRAG documents and return the raw matching chunks."""
            return self._fence_search_response(await search_tool(search_query))

        def calculator(expression: str) -> dict[str, Any]:
            """Evaluate a numeric arithmetic expression."""
            return _calculate(expression)

        async def opensearch_url_ingestion_flow(
            input_value: str, session_id: str | None = None
        ) -> dict[str, Any]:
            """Read a user-provided public URL; use only for an explicit http(s) URL request."""
            del session_id
            return await _read_public_url(input_value)

        return (
            Agent(
                model,
                system_prompt=getattr(agent_config, "system_prompt", None) or DEFAULT_SYSTEM_PROMPT,
                tools=[search_documents, raw_search, calculator, opensearch_url_ingestion_flow],
            ),
            model_name,
        )

    @staticmethod
    def _fence_search_response(response: dict[str, Any]) -> dict[str, Any]:
        """Fence retrieved document text before it enters the model context.

        Search results are later returned to the client as citations, so the
        original result must not be mutated. The stream adapter removes the
        fence markers from its display-only payload after Pydantic AI receives
        this protected copy.
        """
        fenced = copy.deepcopy(response)
        for result in fenced.get("results", []):
            if isinstance(result, dict) and isinstance(result.get("text"), str):
                result["text"] = fence_untrusted_text(result["text"])
        return fenced

    @staticmethod
    def _stream_events(
        event: Any,
        conversation_id: str,
        model: str,
        call_inputs: dict[str, dict[str, Any]],
        call_item_ids: dict[int, str],
    ) -> list[dict[str, Any]]:
        if isinstance(event, PartStartEvent):
            if isinstance(event.part, TextPart) and event.part.content:
                return [NativeChatAgent._text_chunk(conversation_id, model, event.part.content)]
            if isinstance(event.part, ToolCallPart):
                call_inputs[event.part.tool_call_id] = NativeChatAgent._arguments(event.part.args)
                item_id = event.part.id or f"fc_{event.part.tool_call_id}"
                call_item_ids[event.index] = item_id
                return [
                    {
                        "item": {
                            "arguments": "",
                            "call_id": event.part.tool_call_id,
                            "name": event.part.tool_name,
                            "type": "function_call",
                            "id": item_id,
                            "status": "in_progress",
                        },
                        "output_index": event.index,
                        "sequence_number": None,
                        "type": "response.output_item.added",
                    }
                ]
        if isinstance(event, PartDeltaEvent):
            if isinstance(event.delta, TextPartDelta):
                return [
                    NativeChatAgent._text_chunk(conversation_id, model, event.delta.content_delta)
                ]
            if isinstance(event.delta, ToolCallPartDelta):
                delta = event.delta.args_delta
                if delta:
                    return [
                        {
                            "item_id": event.delta.tool_call_id
                            or call_item_ids.get(event.index, ""),
                            "output_index": event.index,
                            "sequence_number": None,
                            "type": "response.function_call_arguments.delta",
                            "delta": delta if isinstance(delta, str) else json.dumps(delta),
                        }
                    ]
        if isinstance(event, PartEndEvent) and isinstance(event.part, ToolCallPart):
            arguments = (
                event.part.args
                if isinstance(event.part.args, str)
                else json.dumps(event.part.args or {})
            )
            call_inputs[event.part.tool_call_id] = NativeChatAgent._arguments(event.part.args)
            return [
                {
                    "arguments": arguments,
                    "item_id": event.part.id
                    or call_item_ids.get(event.index)
                    or f"fc_{event.part.tool_call_id}",
                    "name": None,
                    "output_index": event.index,
                    "sequence_number": None,
                    "type": "response.function_call_arguments.done",
                }
            ]
        if isinstance(event, FunctionToolResultEvent):
            result = _tool_result(event.part.content)
            return [
                {
                    "item": {
                        "id": f"{event.part.tool_name}_{event.part.tool_call_id}",
                        "content": None,
                        "role": None,
                        "status": "completed" if event.part.outcome == "success" else "failed",
                        "type": "tool_call",
                        "phase": None,
                        "inputs": call_inputs.get(event.part.tool_call_id, {}),
                        "tool_name": event.part.tool_name,
                        "results": result.get("results", result),
                    },
                    "output_index": 0,
                    "sequence_number": None,
                    "type": "response.output_item.done",
                }
            ]
        return []

    @staticmethod
    def _arguments(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return {}
        try:
            result = json.loads(value)
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _text_chunk(conversation_id: str, model: str, content: str) -> dict[str, Any]:
        return {
            "sequence_number": None,
            "type": None,
            "id": conversation_id,
            "object": "response.chunk",
            "created": int(time.time()),
            "model": model,
            "status": None,
            "finish_reason": None,
            "delta": {"content": content},
        }

    @staticmethod
    def _completed_events(conversation_id: str, model: str, result: Any) -> list[dict[str, Any]]:
        return [
            {
                "sequence_number": None,
                "type": None,
                "id": conversation_id,
                "object": "response.chunk",
                "created": int(time.time()),
                "model": model,
                "status": "completed",
                "finish_reason": "stop",
                "delta": {},
            },
            {
                "response": {
                    "id": conversation_id,
                    "object": "response",
                    "created_at": time.time(),
                    "model": model,
                    "status": "completed",
                    "usage": NativeChatAgent._usage_data(result),
                },
                "sequence_number": None,
                "type": "response.completed",
            },
        ]

    async def _save_turn(
        self,
        conversation_id: str,
        user_id: str,
        response: str,
        chunks: list[dict[str, Any]],
        result: Any,
    ) -> None:
        await native_chat_history_service.append(
            conversation_id,
            user_id,
            "assistant",
            content=response,
            event_data={
                "chunks": chunks,
                "pydantic_messages": json.loads(result.new_messages_json()),
                "usage": self._usage_data(result),
            },
        )

    async def _save_completed_turn(
        self,
        conversation_id: str,
        user_id: str,
        response: str,
        chunks: list[dict[str, Any]],
        result: Any,
    ) -> None:
        try:
            await self._save_turn(conversation_id, user_id, response, chunks, result)
        except Exception:
            logger.exception(
                "[CHAT] Failed to persist completed native chat turn",
                conversation_id=conversation_id,
            )

    @staticmethod
    def _usage_data(result: Any) -> dict[str, Any]:
        """Make Pydantic AI usage safe for SQLAlchemy's JSON column."""
        return json.loads(json.dumps(asdict(result.usage), default=str))

    @staticmethod
    def _sources(messages: list[Any]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for message in messages:
            for part in getattr(message, "parts", []):
                if getattr(part, "tool_name", None) not in {"search_documents", "raw_search"}:
                    continue
                content = getattr(part, "content", None)
                if isinstance(content, dict):
                    results = copy.deepcopy(content.get("results") or [])
                    strip_untrusted_fence_recursive(results)
                    sources.extend(results)
        return sources

    @staticmethod
    def _require_response_text(response: str) -> None:
        if not response.strip():
            from services.llm_gateway import LlmGatewayError

            raise LlmGatewayError(
                "The language model returned an empty response. Please try again or choose another model.",
                502,
                detail="native agent completed without response text",
            )

    @staticmethod
    def _event(payload: dict[str, Any]) -> bytes:
        return (json.dumps(payload, default=str) + "\n").encode()

    @staticmethod
    def _public_error_message(exc: Exception) -> str:
        from services.llm_gateway import LlmGatewayError

        if isinstance(exc, LlmGatewayError):
            return exc.message
        return "The chat request could not be completed. Please try again."


native_chat_agent = NativeChatAgent()
