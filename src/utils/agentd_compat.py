"""Compatibility shim for the synthetic Responses API events agentd emits.

When a streamed response contains a tool call, agentd synthesizes the
`response.function_call_arguments.*` events itself rather than forwarding the
provider's. Its constructor call omits `name`, which openai>=2.x marks required
on `ResponseFunctionCallArgumentsDoneEvent`, so pydantic raises inside agentd's
async generator. That exception escapes through our StreamingResponse after the
response headers are already on the wire, so the connection is cut mid-body and
the browser reports a dropped request rather than an error the UI can render.
Net effect: streaming chat dies the moment retrieval runs, while non-streaming
chat (which never builds these events) works.

agentd 0.8.7 and 0.8.8 both omit the field, so there is no version to upgrade
to. Relax it here until it is fixed upstream — the value is unused by every
consumer of this stream: our own parsers key off `type`/`item_id`, and the
frontend reads the tool name from `response.output_item.*` instead.
"""

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Event class -> {field agentd omits: default to substitute}. Keep this as tight
# as possible: each entry weakens validation of a provider payload, so add one
# only for a field agentd genuinely never passes.
_RELAXED_FIELDS: dict[str, dict[str, object]] = {
    "ResponseFunctionCallArgumentsDoneEvent": {"name": ""},
}


def apply_agentd_openai_compat() -> None:
    """Make the fields agentd omits optional. Safe to call more than once.

    A no-op when the installed SDK already treats them as optional, so this
    disappears on its own once agentd or the SDK catches up.
    """
    try:
        from openai.types import responses as openai_responses
    except Exception as e:  # pragma: no cover - openai is a hard dependency
        logger.warning("Could not apply agentd compatibility shim", error=str(e))
        return

    for class_name, defaults in _RELAXED_FIELDS.items():
        event_class = getattr(openai_responses, class_name, None)
        if event_class is None:
            continue

        relaxed = []
        for field_name, default in defaults.items():
            field = event_class.model_fields.get(field_name)
            if field is None or not field.is_required():
                continue
            field.default = default
            relaxed.append(field_name)

        if relaxed:
            event_class.model_rebuild(force=True)
            # NB: "event" is structlog's own message key — don't pass it as a
            # binding here.
            logger.debug(
                "Relaxed required fields agentd does not populate",
                event_class=class_name,
                fields=relaxed,
            )
