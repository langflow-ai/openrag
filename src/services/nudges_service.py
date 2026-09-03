"""Nudge generation without Langflow.

Nudges are the three suggested prompts under the chat input. By default they
come from the `openrag_nudges` Langflow flow; when the Langflow chat bypass is
active (`DISABLE_CHAT_WITH_LANGFLOW`) they are generated here instead:
OpenSearch retrieval plus one plain LLM completion, reproducing what the flow's
graph did.

The prompt template is copied verbatim from `flows/openrag_nudges.json`
(node `Prompt Template-Wo6kR`) so both paths ask the model for the same thing.
The wire contract is unchanged either way: `{"response": "a\\nb\\nc"}`, which
the frontend splits on newlines.
"""

import json
import re
from typing import Any

from services.llm_gateway import LlmGatewayError, chat_completions
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Copied verbatim from flows/openrag_nudges.json -> "Prompt Template-Wo6kR".
# The only braces in it are {prompt} and {docs}; str.format does not re-scan
# substituted values, so untrusted document text containing braces is inert.
# Do not switch this to chained .replace(), which is order-dependent.
NUDGES_PROMPT_TEMPLATE = """You are generating prompt nudges to help a user explore a corpus.

Task:
1) Skim the documents to infer common themes, entities, or tasks.
2) Propose exactly three concise, distinct prompt nudges (close to 40 characters each) that encourage useful next queries.
3) Ensure the nudges are questions or commands that the user can send to the chatbot.
4) Return strings only, separated by a newline. Do not include quotation marks.
5) If an error occurs, return a blank string.

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
{docs}"""  # noqa: E501

MAX_HISTORY_MESSAGES = 8
MAX_NUDGES = 3
# Matches number_of_results on the flow's OpenSearch node.
DEFAULT_NUDGE_DOC_LIMIT = 10
# A nudge is meant to be ~40 characters; anything this long is prose the model
# wrapped around its answer, not a nudge.
MAX_NUDGE_CHARS = 200
# Match the flow's OpenAICompatibleLLM node so both paths are equally repeatable.
NUDGE_TEMPERATURE = 0.1
NUDGE_SEED = 1

_BULLET_RE = re.compile(r"^(?:[-*+•–—]+\s*|\d+[.)]\s*|\(\d+\)\s*)")
_SEPARATOR_RE = re.compile(r"^[-=_*\s]+$")
_QUOTE_CHARS = "\"'`“”‘’"


def _trim_results(r, depth=0):
    """Bound tool-result payloads before they go into the history prompt.

    Moved verbatim from ChatService.langflow_nudges_chat; the original was a
    closure that captured nothing.
    """
    MAX_DEPTH = 3
    MAX_LIST_LEN = 3
    MAX_DICT_KEYS = 5
    MAX_STR_LEN = 1000

    if isinstance(r, str):
        return r[:MAX_STR_LEN] + ("..." if len(r) > MAX_STR_LEN else "")
    elif isinstance(r, list):
        if depth >= MAX_DEPTH:
            return "[Max depth reached]"
        return [_trim_results(x, depth + 1) for x in r[:MAX_LIST_LEN]]
    elif isinstance(r, dict):
        if depth >= MAX_DEPTH:
            return "[Max depth reached]"
        trimmed = {}
        for i, (k, v) in enumerate(r.items()):
            if i >= MAX_DICT_KEYS:
                trimmed["_more_keys"] = f"... ({len(r) - MAX_DICT_KEYS} omitted)"
                break
            trimmed[k] = _trim_results(v, depth + 1)
        return trimmed
    return r


async def build_history_prompt(
    conversation_user_id: str | None,
    previous_response_id: str | None,
) -> str:
    """Render recent conversation turns into the `{prompt}` half of the template.

    Returns "" when there is no conversation to summarise, which is the signal
    to fall back to knowledge-base nudges. Shared by the Langflow and the
    langflowless paths so both produce identical prompts.
    """
    prompt = ""
    if previous_response_id:
        messages = []
        # Try in-memory active conversation first
        from agent import active_conversations

        if (
            conversation_user_id in active_conversations
            and previous_response_id in active_conversations[conversation_user_id]
        ):
            messages = active_conversations[conversation_user_id][previous_response_id].get(
                "messages", []
            )

        # Filter out system messages
        user_ast_messages = [m for m in messages if m.get("role") in ["user", "assistant"]]

        # If no history in memory, try fetching from Langflow persistent history
        if not user_ast_messages:
            from services.langflow_history_service import langflow_history_service

            try:
                lf_messages = await langflow_history_service.get_session_messages(
                    conversation_user_id, previous_response_id
                )
                if lf_messages:
                    messages = lf_messages
                    user_ast_messages = [
                        m for m in messages if m.get("role") in ["user", "assistant"]
                    ]
            except Exception as e:
                logger.warning(f"Failed to fetch session messages for nudges: {e}")

        if user_ast_messages:
            # Return at max 8 messages (the last ones)
            user_ast_messages = user_ast_messages[-MAX_HISTORY_MESSAGES:]

            formatted_messages = []

            for msg in user_ast_messages:
                role = msg.get("role")
                content = msg.get("content", "")
                msg_str = f"{role}: {content}"

                # Extract tool calls and chunks if this is an assistant message
                if role == "assistant":
                    extracted_chunks = []

                    # 1. From chunks list
                    chunks = msg.get("chunks") or []
                    if isinstance(chunks, list):
                        last_tc = None
                        for chunk in chunks:
                            if isinstance(chunk, dict):
                                item = chunk.get("item", {})
                                if isinstance(item, dict) and item.get("type") in [
                                    "tool_call",
                                    "retrieval_call",
                                ]:
                                    t_name = item.get("tool_name") or item.get("name") or "tool"
                                    res = _trim_results(item.get("results"))
                                    tc = {"tool_name": t_name, "results": res}
                                    extracted_chunks.append(tc)
                                    last_tc = tc
                                elif chunk.get("type") in [
                                    "response.tool_call.result",
                                    "tool_call_result",
                                ]:
                                    res = _trim_results(chunk.get("result") or chunk)
                                    if last_tc:
                                        last_tc["results"] = res
                                    else:
                                        extracted_chunks.append(
                                            {"tool_name": "tool", "results": res}
                                        )

                    # 2. From response_data dict/string
                    resp_data = msg.get("response_data")
                    if resp_data:
                        if isinstance(resp_data, str):
                            try:
                                resp_data = json.loads(resp_data)
                            except Exception:
                                resp_data = {}
                        if isinstance(resp_data, dict):
                            t_calls = resp_data.get("tool_calls") or []
                            if isinstance(t_calls, list):
                                for tc in t_calls:
                                    if isinstance(tc, dict):
                                        t_name = tc.get("name")
                                        func = tc.get("function")
                                        if isinstance(func, dict) and not t_name:
                                            t_name = func.get("name")
                                        res = _trim_results(tc.get("result"))
                                        extracted_chunks.append(
                                            {"tool_name": t_name or "tool", "results": res}
                                        )

                    if extracted_chunks:
                        chunks_strs = []
                        for tc in extracted_chunks:
                            t_name = tc.get("tool_name", "tool")
                            res = tc.get("results")
                            if res is not None:
                                res_str = json.dumps(res, ensure_ascii=False, default=str)
                                chunks_strs.append(f"[Tool: {t_name}, Results: {res_str}]")
                        if chunks_strs:
                            msg_str += "\nContext Chunks:\n" + "\n".join(chunks_strs)

                formatted_messages.append(msg_str)

            prompt = "\n\n".join(formatted_messages)

    return prompt


def parse_nudges(text: str | None) -> list[str]:
    """Turn a model reply into at most three clean nudge strings.

    The prompt asks for bare newline-separated strings, but models wrap them in
    numbering, bullets, quotes, fences or a "Here are three nudges:" preamble.
    Strip all of that rather than letting it reach the UI as button labels.
    """
    if not text or not text.strip():
        return []

    body = text.strip()

    # Unwrap a fenced block: ```\n...\n``` or ```json\n...\n```
    if body.startswith("```"):
        lines = body.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines).strip()

    # Unwrap a JSON array, which models emit despite "strings only".
    if body.startswith("["):
        try:
            decoded = json.loads(body)
        except (ValueError, TypeError):
            pass
        else:
            if isinstance(decoded, list):
                body = "\n".join(str(item) for item in decoded)

    nudges: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        candidate = line.strip()
        if not candidate or _SEPARATOR_RE.match(candidate):
            continue

        candidate = _BULLET_RE.sub("", candidate)
        candidate = candidate.strip(_QUOTE_CHARS).strip().rstrip(",;")
        candidate = " ".join(candidate.split())

        if not candidate or len(candidate) > MAX_NUDGE_CHARS:
            continue
        # Drops preambles ("Here are three nudges:") without ever dropping a
        # real nudge, which is a question or an imperative.
        if candidate.endswith(":"):
            continue

        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        nudges.append(candidate)
        if len(nudges) >= MAX_NUDGES:
            break

    return nudges


async def _retrieve_documents(
    search_service,
    *,
    user_id: str | None,
    jwt_token: str | None,
    filters: dict | None,
    limit: int | None,
    score_threshold: float | None,
    exclude_sample_data: bool,
) -> list[str]:
    """Fetch corpus text for the `{docs}` half of the template.

    Mirrors the flow's OpenSearch node: a match-all sweep of the corpus, capped
    at the same default of 10 chunks. Retrieval failures are not worth failing
    a decorative feature over, so they degrade to no documents.
    """
    if search_service is None:
        logger.warning("[NUDGES] Search service unavailable; skipping retrieval")
        return []

    try:
        result = await search_service.search(
            "*",
            user_id=user_id,
            jwt_token=jwt_token,
            filters=filters,
            limit=limit or DEFAULT_NUDGE_DOC_LIMIT,
            score_threshold=score_threshold or 0,
            exclude_sample_data=exclude_sample_data,
        )
    except Exception as exc:
        logger.warning("[NUDGES] Document retrieval failed", error=str(exc))
        return []

    return [
        chunk["text"]
        for chunk in (result.get("results") or [])
        if isinstance(chunk.get("text"), str) and chunk["text"].strip()
    ]


async def generate_nudges(
    *,
    search_service,
    user_id: str | None = None,
    jwt_token: str | None = None,
    conversation_user_id: str | None = None,
    previous_response_id: str | None = None,
    filters: dict | None = None,
    limit: int | None = None,
    score_threshold: float | None = None,
) -> dict[str, str]:
    """Generate nudges in-process, without Langflow.

    Returns the same shape the Langflow path returns, minus `response_id`
    (nothing consumes it, and there is no conversation to point at).
    """
    # An empty list means "no filter" upstream, but SearchService reads it as
    # "match nothing" (it maps [] to an impossible term). Drop empty lists so a
    # cleared filter chip does not silently kill nudges.
    active_filters = {
        key: values
        for key, values in (filters or {}).items()
        if isinstance(values, list) and values
    }

    history_prompt = await build_history_prompt(conversation_user_id, previous_response_id)

    # The flow always retrieved and then told the model to ignore {docs} when
    # history was present. Skip the round-trip instead. Keying off the rendered
    # history (not previous_response_id) means a failed history lookup still
    # falls back to knowledge-base nudges.
    docs: list[str] = []
    if not history_prompt:
        docs = await _retrieve_documents(
            search_service,
            user_id=user_id,
            jwt_token=jwt_token,
            filters=active_filters or None,
            limit=limit,
            score_threshold=score_threshold,
            exclude_sample_data=not active_filters,
        )

    if not history_prompt and not docs:
        logger.info("[NUDGES] No chat history and no documents; returning no nudges")
        return {"response": ""}

    prompt = NUDGES_PROMPT_TEMPLATE.format(prompt=history_prompt, docs="\n".join(docs))

    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": NUDGE_TEMPERATURE,
        "seed": NUDGE_SEED,
    }
    # No "model" key on purpose: the gateway then resolves agent.llm_model /
    # agent.llm_provider, which is what SELECTED_LANGUAGE_MODEL resolved to in
    # the flow. No max_tokens either — the flow leaves it unset, and a small cap
    # starves reasoning models; parse_nudges is the real bound.
    try:
        payload = await chat_completions(body)
    except LlmGatewayError as exc:
        # Never log exc.detail: it carries upstream response bodies.
        logger.warning("[NUDGES] LLM call failed", status_code=exc.status_code, error=exc.message)
        return {"response": ""}

    if not isinstance(payload, dict):
        logger.warning("[NUDGES] Unexpected streaming payload from the LLM gateway")
        return {"response": ""}

    choices = payload.get("choices") or []
    message = (choices[0].get("message") if choices else None) or {}
    nudges = parse_nudges(message.get("content"))

    logger.info(
        "[NUDGES] Generated nudges",
        count=len(nudges),
        used_history=bool(history_prompt),
        doc_count=len(docs),
    )
    return {"response": "\n".join(nudges)}
