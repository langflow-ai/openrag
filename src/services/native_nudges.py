"""Nudges (suggested prompts) without Langflow.

Replaces the Langflow nudges flow (`flows/openrag_nudges.json`) with one
structured-output LLM call through the in-process LLM gateway. The prompt is
ported from the flow's Prompt Template, and documents come from the same hybrid
search the flow runs. The response keeps the flow's shape,
`{"response": "<nudge>\\n<nudge>\\n<nudge>"}`, so the frontend is unchanged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from config.settings import get_openrag_config
from services.llm_gateway import chat_completions, model_capabilities, qualified_model_id
from utils.langflow_utils import fence_untrusted_text
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_NUDGES = 3
DEFAULT_DOCUMENT_LIMIT = 10
MAX_DOCUMENT_CHARS = 2000
# The flow's search query: the two-character string `""`, not an empty one.
# The OpenSearch component skips the search only for a blank query, so this
# runs a real hybrid search, and the ranking comes from it.
FLOW_SEARCH_QUERY = '""'

# Ported verbatim from the Prompt Template in flows/openrag_nudges.json, except
# rules 4 and 5, which ask for the JSON shape the structured call returns.
NUDGES_PROMPT = """You are generating prompt nudges to help a user explore a corpus.

Task:
1) Skim the documents to infer common themes, entities, or tasks.
2) Propose exactly three concise, distinct prompt nudges (close to 40 characters each) that encourage useful next queries.
3) Ensure the nudges are questions or commands that the user can send to the chatbot.
4) Return a JSON object {{"nudges": [...]}} holding the nudge strings. Do not include quotation marks inside the strings.
5) If an error occurs, return {{"nudges": []}}.

Rules: Be brief. No duplicates. No explanations outside the strings of the nudges. English only.

If chat history is provided, follow these rules:
1) Generate recommendations based solely on the chat history and its chunks, not on the documents.
2) Generate new questions that the user might have based on the LLM's response to their previous query. DO NOT repeat user questions.
3) Match the style of the previous questions (e.g., if the user asked a question, generate nudges as questions).

Examples:
  What are this quarter's top 10 deals?
  Summarize recent client interactions
  Search OpenSearch for mentions of our competitors

--------------------------------------------------------

Chat history:
{prompt}


--------------------------------------------------------

Documents (ignore if chat history is not empty):
{docs}
"""


class NudgeSuggestions(BaseModel):
    """The model's reply: the nudge strings."""

    model_config = ConfigDict(extra="forbid")

    nudges: list[str]


_SCHEMA = NudgeSuggestions.model_json_schema()
_TOOL_NAME = "suggest_nudges"
_JSON_SCHEMA_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "nudges", "strict": True, "schema": _SCHEMA},
}
_NUDGES_TOOL = {
    "type": "function",
    "function": {
        "name": _TOOL_NAME,
        "description": "Return the prompt nudges.",
        "parameters": _SCHEMA,
    },
}
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

Completion = Callable[..., Awaitable[Any]]
Capabilities = Callable[..., frozenset[str]]


def _output_mode(model_id: str, cfg: Any, capabilities: Capabilities) -> str:
    """`json_schema`, or `tool` for a model that can call tools but not take a schema.

    The gateway drops parameters a provider does not support, so sending a
    schema the model cannot honour fails silently. An unknown model gets the
    schema; its reply is validated either way.
    """
    flags = capabilities(model_id, config=cfg)
    if "structured_output" not in flags and "function_calling" in flags:
        return "tool"
    return "json_schema"


def _reply_json(payload: Any, mode: str) -> str:
    """The JSON text to validate: the tool call's arguments, or the message content."""
    choices = (payload or {}).get("choices") or [{}]
    message = choices[0].get("message") or {}
    if mode == "tool":
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if function.get("name") == _TOOL_NAME:
                arguments = function.get("arguments")
                return arguments if isinstance(arguments, str) else json.dumps(arguments)
        return ""
    return _CODE_FENCE.sub("", (message.get("content") or "").strip())


def parse_suggestions(text: str) -> list[str]:
    """Validated nudges, cleaned and deduplicated. Empty when the reply is malformed."""
    try:
        suggestions = NudgeSuggestions.model_validate_json(text)
    except ValidationError:
        return []
    nudges: list[str] = []
    for item in suggestions.nudges:
        nudge = item.strip().strip("\"'").strip()
        if nudge and nudge not in nudges:
            nudges.append(nudge)
        if len(nudges) == MAX_NUDGES:
            break
    return nudges


def _without_empty_lists(filters: dict | None) -> dict:
    """Drop empty-list filters: the flow ignores them, but search treats them as match-nothing."""
    return {key: value for key, value in (filters or {}).items() if value != []}


async def sample_documents(
    search_service: Any,
    *,
    user_id: str | None,
    jwt_token: str | None,
    filters: dict | None,
    limit: int | None,
    score_threshold: float | None = None,
) -> list[str]:
    """Chunk texts for a new chat, from the same hybrid search the flow runs.

    Runs as the caller, so document-level security applies. Sample data is left
    out unless the user selected a filter, as in the flow. A failure yields no
    documents: nudges are best effort.
    """
    search_filters = _without_empty_lists(filters)
    size = min(limit, DEFAULT_DOCUMENT_LIMIT) if limit and limit > 0 else DEFAULT_DOCUMENT_LIMIT
    try:
        response = await search_service.search(
            FLOW_SEARCH_QUERY,
            user_id=user_id,
            jwt_token=jwt_token,
            filters=search_filters,
            limit=size,
            score_threshold=score_threshold or 0,
            source="nudges",
            exclude_sample_data=not search_filters,
        )
    except Exception as exc:
        logger.warning("Nudges document search failed", error=str(exc))
        return []
    texts = []
    for chunk in (response or {}).get("results") or []:
        text = chunk.get("text") if isinstance(chunk, dict) else None
        if isinstance(text, str) and text.strip():
            texts.append(text[:MAX_DOCUMENT_CHARS])
    return texts


async def generate_nudges(
    *,
    history_prompt: str,
    documents: list[str],
    config: Any = None,
    complete: Completion | None = None,
    capabilities: Capabilities | None = None,
) -> dict[str, str]:
    """One LLM call for up to three nudges, in the flow's `{"response": ...}` shape."""
    cfg = config or get_openrag_config()
    model = (getattr(cfg.agent, "llm_model", "") or "").strip()
    if not model:
        logger.warning("Nudges skipped: no language model is configured")
        return {"response": ""}

    model_id = qualified_model_id(getattr(cfg.agent, "llm_provider", None), model)
    mode = _output_mode(model_id, cfg, capabilities or model_capabilities)
    docs = "\n\n".join(fence_untrusted_text(text) for text in documents)
    body: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": NUDGES_PROMPT.format(prompt=history_prompt, docs=docs)}
        ],
        "temperature": 0.1,
        "seed": 1,
        "stream": False,
    }
    if mode == "tool":
        body["tools"] = [_NUDGES_TOOL]
        body["tool_choice"] = {"type": "function", "function": {"name": _TOOL_NAME}}
    else:
        body["response_format"] = _JSON_SCHEMA_FORMAT
    payload = await (complete or chat_completions)(body, config=cfg)
    nudges = parse_suggestions(_reply_json(payload, mode))
    if not nudges:
        logger.warning("Nudges reply did not match the schema", output_mode=mode)
    return {"response": "\n".join(nudges)}
