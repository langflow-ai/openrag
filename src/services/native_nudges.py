"""Nudges (suggested prompts) without Langflow.

Replaces the Langflow nudges flow (`flows/openrag_nudges.json`) with one
structured-output LLM call through the in-process LLM gateway. The prompt is
ported from the flow's Prompt Template. The response keeps the flow's shape,
`{"response": "<nudge>\\n<nudge>\\n<nudge>"}`, so the frontend is unchanged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from config.settings import get_index_name, get_openrag_config
from services.llm_gateway import chat_completions, qualified_model_id
from utils.langflow_utils import fence_untrusted_text
from utils.logging_config import get_logger
from utils.opensearch_queries import build_filter_clauses

logger = get_logger(__name__)

MAX_NUDGES = 3
DEFAULT_DOCUMENT_LIMIT = 10
MAX_DOCUMENT_CHARS = 2000

# Ported verbatim from the Prompt Template in flows/openrag_nudges.json, except
# rule 4, which asks for the JSON shape the structured call returns.
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

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "nudges",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "nudges": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["nudges"],
            "additionalProperties": False,
        },
    },
}

_SAMPLE_DATA_EXCLUSION = {"bool": {"must_not": [{"term": {"is_sample_data": "true"}}]}}
_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

Completion = Callable[..., Awaitable[Any]]


def parse_nudges(text: str | None) -> list[str]:
    """Nudge strings from the model's reply: JSON first, then one per line."""
    raw = _CODE_FENCE.sub("", (text or "").strip())
    if not raw:
        return []

    candidates: list[Any]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        candidates = raw.splitlines()
    else:
        if isinstance(parsed, Mapping):
            candidates = parsed.get("nudges") or []
        elif isinstance(parsed, list):
            candidates = parsed
        else:
            candidates = []

    nudges: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            continue
        nudge = _LIST_MARKER.sub("", item).strip().strip("\"'").strip()
        if nudge and nudge not in nudges:
            nudges.append(nudge)
        if len(nudges) == MAX_NUDGES:
            break
    return nudges


async def sample_documents(
    opensearch_client: Any,
    index_name: str | None = None,
    *,
    filters: dict | None,
    limit: int | None,
    score_threshold: float | None = None,
) -> list[str]:
    """Chunk texts from the user's corpus, narrowed by the selected knowledge filter.

    Uses the caller's own OpenSearch client, so document-level security applies.
    Sample data is left out unless the user selected a filter, as in the flow.
    A failure yields no documents: nudges are best effort.
    """
    filter_clauses = build_filter_clauses(filters)
    if not filter_clauses:
        filter_clauses.append(_SAMPLE_DATA_EXCLUSION)
    body: dict[str, Any] = {
        "size": limit or DEFAULT_DOCUMENT_LIMIT,
        "_source": ["text"],
        "query": {"bool": {"must": [{"match_all": {}}], "filter": filter_clauses}},
    }
    if score_threshold:
        body["min_score"] = score_threshold
    try:
        response = await opensearch_client.search(index=index_name or get_index_name(), body=body)
    except Exception as exc:
        logger.warning("Nudges document sample failed", error=str(exc))
        return []
    hits = (response or {}).get("hits", {}).get("hits", [])
    texts = []
    for hit in hits:
        text = (hit.get("_source") or {}).get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text[:MAX_DOCUMENT_CHARS])
    return texts


async def generate_nudges(
    *,
    history_prompt: str,
    documents: list[str],
    config: Any = None,
    complete: Completion | None = None,
) -> dict[str, str]:
    """One LLM call for up to three nudges, in the flow's `{"response": ...}` shape."""
    cfg = config or get_openrag_config()
    model = (getattr(cfg.agent, "llm_model", "") or "").strip()
    if not model:
        logger.warning("Nudges skipped: no language model is configured")
        return {"response": ""}

    docs = "\n\n".join(fence_untrusted_text(text) for text in documents)
    body = {
        "model": qualified_model_id(getattr(cfg.agent, "llm_provider", None), model),
        "messages": [
            {"role": "user", "content": NUDGES_PROMPT.format(prompt=history_prompt, docs=docs)}
        ],
        "temperature": 0.1,
        "stream": False,
        "response_format": _RESPONSE_FORMAT,
    }
    payload = await (complete or chat_completions)(body, config=cfg)
    choices = (payload or {}).get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content") or ""
    return {"response": "\n".join(parse_nudges(content))}
