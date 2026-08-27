"""Unit tests for the agentd Responses API compatibility shim.

agentd synthesizes `response.function_call_arguments.done` without a `name`.
openai>=2.x requires it, and the resulting ValidationError escapes agentd's
async generator mid-stream, cutting the StreamingResponse connection — so
streaming chat dies as soon as a tool call happens.
"""

import pytest
from openai.types.responses import ResponseFunctionCallArgumentsDoneEvent
from pydantic import ValidationError

from utils.agentd_compat import apply_agentd_openai_compat


def _build_like_agentd():
    """Exactly the constructor call agentd makes (agentd/patch.py:767)."""
    return ResponseFunctionCallArgumentsDoneEvent(
        arguments='{"query": "costco earnings"}',
        item_id="fc_1",
        output_index=0,
        sequence_number=2,
        type="response.function_call_arguments.done",
    )


def test_done_event_builds_without_name():
    apply_agentd_openai_compat()
    event = _build_like_agentd()
    assert event.type == "response.function_call_arguments.done"
    assert event.arguments == '{"query": "costco earnings"}'


def test_shim_is_idempotent():
    apply_agentd_openai_compat()
    apply_agentd_openai_compat()
    assert _build_like_agentd().item_id == "fc_1"


def test_shim_only_relaxes_the_omitted_field():
    """Fields agentd does populate must still be validated."""
    apply_agentd_openai_compat()

    with pytest.raises(ValidationError):
        ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc_1",
            output_index=0,
            sequence_number=2,
            type="response.function_call_arguments.done",
        )  # missing `arguments`

    still_required = {
        name
        for name, field in ResponseFunctionCallArgumentsDoneEvent.model_fields.items()
        if field.is_required()
    }
    assert {"arguments", "item_id", "output_index", "sequence_number"} <= still_required
