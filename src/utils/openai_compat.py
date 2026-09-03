"""Compatibility shims for OpenAI SDK model changes used by integrations."""

from typing import Any


def install_agentd_response_event_compat(agentd_patch_module: Any) -> None:
    """Patch agentd's synthetic Responses event for newer OpenAI SDKs.

    agentd emits ResponseFunctionCallArgumentsDoneEvent for streamed tool calls.
    Recent OpenAI SDK versions require a ``name`` field on that event, while the
    current agentd release does not pass one. Fill a generic fallback so the
    stream can continue; the adjacent output item still carries the real tool
    name for UI display.
    """
    original = agentd_patch_module.ResponseFunctionCallArgumentsDoneEvent
    if getattr(original, "_openrag_name_compat", False):
        return

    def response_function_call_arguments_done_event_compat(*args, **kwargs):
        kwargs.setdefault("name", "function_call")
        return original(*args, **kwargs)

    response_function_call_arguments_done_event_compat._openrag_name_compat = True
    agentd_patch_module.ResponseFunctionCallArgumentsDoneEvent = (
        response_function_call_arguments_done_event_compat
    )
