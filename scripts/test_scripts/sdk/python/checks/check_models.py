"""Checks for client.models — list models per provider."""

from harness import Check, Context, Skip
from openrag_sdk.exceptions import OpenRAGError

PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"]


def _make_check(provider: str):
    async def fn(ctx: Context) -> None:
        try:
            models = await ctx.client.models.list(provider)
        except OpenRAGError as e:
            # SaaS deployments typically enable only a subset of providers.
            raise Skip(f"provider '{provider}' not available: {e}") from e
        assert isinstance(models.language_models, list), "language_models not a list"
        assert isinstance(models.embedding_models, list), "embedding_models not a list"

    return fn


CHECKS = [Check(f"models.list_{p}", _make_check(p)) for p in PROVIDERS]
