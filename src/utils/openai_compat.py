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
    original_done = agentd_patch_module.ResponseFunctionCallArgumentsDoneEvent
    if getattr(original_done, "_openrag_name_compat", False):
        return
    original_added = agentd_patch_module.ResponseOutputItemAddedEvent
    names_by_item_id: dict[str, str] = {}

    def response_output_item_added_event_compat(*args: Any, **kwargs: Any) -> Any:
        event = original_added(*args, **kwargs)
        item = getattr(event, "item", None)
        item_id = getattr(item, "id", None)
        name = getattr(item, "name", None)
        if isinstance(item_id, str) and isinstance(name, str):
            names_by_item_id[item_id] = name
        return event

    def response_function_call_arguments_done_event_compat(*args: Any, **kwargs: Any) -> Any:
        item_id = kwargs.get("item_id")
        if item_id is None and len(args) > 1:
            item_id = args[1]
        if "name" not in kwargs:
            kwargs["name"] = names_by_item_id.pop(str(item_id), "function_call")
        return original_done(*args, **kwargs)

    # Functions do not declare arbitrary attributes to mypy; this marker only
    # guards repeated runtime installation of the compatibility wrapper.
    compatibility_wrapper: Any = response_function_call_arguments_done_event_compat
    compatibility_wrapper._openrag_name_compat = True
    agentd_patch_module.ResponseOutputItemAddedEvent = response_output_item_added_event_compat
    agentd_patch_module.ResponseFunctionCallArgumentsDoneEvent = compatibility_wrapper
