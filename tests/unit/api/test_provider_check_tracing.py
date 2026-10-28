"""Provider checks call LiteLLM directly; their traces say so instead of looking like real traffic."""

import pytest

from api import provider_validation


@pytest.fixture
def tracing_on(monkeypatch):
    from observability import tracing

    monkeypatch.setattr(tracing, "_enabled", True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("litellm_call", "embedding_model", "llm_model", "kind"),
    [
        ("litellm.aembedding", "text-embedding-3-small", None, "embedding"),
        ("litellm.acompletion", None, "gpt-4o-mini", "chat"),
    ],
)
async def test_provider_checks_are_traced_as_provider_checks(
    monkeypatch, tracing_on, litellm_call, embedding_model, llm_model, kind
):
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(litellm_call, _capture)

    await provider_validation._test_litellm_provider(
        provider="openai",
        credentials={"api_key": "k"},
        runtime_kwargs={},
        embedding_model=embedding_model,
        llm_model=llm_model,
    )

    metadata = captured["metadata"]
    assert metadata["generation_name"] == f"{kind}.provider_check"
    assert metadata["trace_metadata"]["openrag.provider"] == "openai"
