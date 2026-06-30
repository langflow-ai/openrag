"""Checks for client.settings — get and update."""

from harness import Check, Context


async def get(ctx: Context) -> None:
    settings = await ctx.client.settings.get()
    assert settings.agent is not None, "settings.agent missing"
    assert settings.knowledge is not None, "settings.knowledge missing"


async def update_roundtrip(ctx: Context) -> None:
    # Safe no-op: re-set the current chunk_size and read it back, so the
    # deployment's configuration is never actually changed.
    current = await ctx.client.settings.get()
    chunk_size = current.knowledge.chunk_size or 1000

    result = await ctx.client.settings.update({"chunk_size": chunk_size})
    assert result.message is not None, "update returned no message"

    updated = await ctx.client.settings.get()
    assert updated.knowledge.chunk_size == chunk_size, (
        f"chunk_size readback mismatch: {updated.knowledge.chunk_size} != {chunk_size}"
    )


CHECKS = [
    Check("settings.get", get),
    Check("settings.update_roundtrip", update_roundtrip, requires=["settings.get"]),
]
