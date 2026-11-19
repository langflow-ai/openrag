from openai.types.responses import (
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
)

from utils.openai_compat import install_agentd_response_event_compat


def test_agentd_function_call_done_event_gets_fallback_name(monkeypatch):
    class FakeAgentDPatch:
        ResponseFunctionCallArgumentsDoneEvent = ResponseFunctionCallArgumentsDoneEvent
        ResponseOutputItemAddedEvent = ResponseOutputItemAddedEvent

    fake_patch = FakeAgentDPatch()

    install_agentd_response_event_compat(fake_patch)

    event = fake_patch.ResponseFunctionCallArgumentsDoneEvent(
        arguments='{"query":"x"}',
        item_id="fc_1",
        output_index=0,
        sequence_number=1,
        type="response.function_call_arguments.done",
    )

    assert event.name == "function_call"


def test_agentd_function_call_done_event_preserves_existing_name():
    class FakeAgentDPatch:
        ResponseFunctionCallArgumentsDoneEvent = ResponseFunctionCallArgumentsDoneEvent
        ResponseOutputItemAddedEvent = ResponseOutputItemAddedEvent

    fake_patch = FakeAgentDPatch()

    install_agentd_response_event_compat(fake_patch)

    event = fake_patch.ResponseFunctionCallArgumentsDoneEvent(
        arguments='{"query":"x"}',
        item_id="fc_1",
        name="search_documents",
        output_index=0,
        sequence_number=1,
        type="response.function_call_arguments.done",
    )

    assert event.name == "search_documents"


def test_agentd_function_call_done_event_uses_matching_tool_name():
    class FakeAgentDPatch:
        ResponseFunctionCallArgumentsDoneEvent = ResponseFunctionCallArgumentsDoneEvent
        ResponseOutputItemAddedEvent = ResponseOutputItemAddedEvent

    fake_patch = FakeAgentDPatch()
    install_agentd_response_event_compat(fake_patch)
    fake_patch.ResponseOutputItemAddedEvent(
        item=ResponseFunctionToolCall(
            arguments='{"query":"x"}',
            call_id="call-1",
            id="fc_1",
            name="search_documents",
            type="function_call",
            status="in_progress",
        ),
        output_index=0,
        sequence_number=0,
        type="response.output_item.added",
    )

    event = fake_patch.ResponseFunctionCallArgumentsDoneEvent(
        arguments='{"query":"x"}',
        item_id="fc_1",
        output_index=0,
        sequence_number=1,
        type="response.function_call_arguments.done",
    )

    assert event.name == "search_documents"
