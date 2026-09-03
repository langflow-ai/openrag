"""The agent-facing search tool exposes only what the model can meaningfully set.

`embedding_model` used to be a parameter. The model cannot know which embedding
space a corpus was indexed under, so it guessed — observed in production as
`{"query": "eBay earnings", "embedding_model": "gpt-4"}`, a chat model. That
value is ignored for a populated corpus (spaces are detected from the index),
but it corrupted the `[SEARCH] Query started` log and, on an empty or degraded
index, built a bogus embedding space in the fallback branches.
"""

import inspect

from agentd.tool_decorator import SCHEMA_REGISTRY

import services.search_service as search_service  # noqa: F401  (registers the tool)


def _schema() -> dict:
    return SCHEMA_REGISTRY["search_tool"]["function"]["parameters"]


def test_the_model_can_only_supply_a_query():
    assert set(_schema()["properties"]) == {"query"}
    assert _schema()["required"] == ["query"]


def test_embedding_model_is_not_settable_by_the_model():
    assert "embedding_model" not in _schema()["properties"]
    assert "embedding_model" not in inspect.signature(search_service.search_tool).parameters


def test_the_service_keeps_its_internal_override():
    """Only the agent-facing wrapper is narrowed; callers that know the space
    (ingest-time probes, tests) still pass it explicitly."""
    method = inspect.signature(search_service.SearchService.search_tool).parameters
    assert "embedding_model" in method
    assert "embedding_model" in inspect.signature(search_service.SearchService.search).parameters
