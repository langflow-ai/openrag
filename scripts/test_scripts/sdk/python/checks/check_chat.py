"""Checks for client.chat — non-streaming, streaming, conversations."""

from harness import Check, Context


def _register_chat_cleanup(ctx: Context, chat_id: str | None) -> None:
    if chat_id:
        ctx.add_cleanup(
            f"delete conversation {chat_id}",
            lambda: ctx.client.chat.delete(chat_id),
        )


async def create_nonstream(ctx: Context) -> None:
    response = await ctx.client.chat.create(message="Say hello in exactly 3 words.")
    _register_chat_cleanup(ctx, response.chat_id)

    assert isinstance(response.response, str) and response.response, (
        "chat returned an empty response"
    )
    assert isinstance(response.sources, list), "chat sources is not a list"
    assert response.chat_id, "chat response carried no chat_id"
    ctx.shared["chat_id"] = response.chat_id


async def create_stream(ctx: Context) -> None:
    collected = ""
    chat_id = None
    async for event in await ctx.client.chat.create(
        message="Say 'test' and nothing else.", stream=True
    ):
        if event.type == "content":
            collected += event.delta
        elif event.type == "done":
            chat_id = event.chat_id
    _register_chat_cleanup(ctx, chat_id)

    assert collected, "streaming chat yielded no content deltas"


async def stream_context_manager(ctx: Context) -> None:
    async with ctx.client.chat.stream(message="Say 'hello' and nothing else.") as stream:
        collected = ""
        async for text in stream.text_stream:
            collected += text
        assert collected, "text_stream yielded no text"
        assert stream.text, "stream.text not accumulated"
        assert stream.chat_id is not None, "stream.chat_id not populated after iteration"
        _register_chat_cleanup(ctx, stream.chat_id)


async def multi_turn(ctx: Context) -> None:
    r1 = await ctx.client.chat.create(message="Remember the number 42.")
    _register_chat_cleanup(ctx, r1.chat_id)
    assert r1.chat_id, "first turn returned no chat_id"

    r2 = await ctx.client.chat.create(
        message="What number did I ask you to remember?", chat_id=r1.chat_id
    )
    assert r2.response, "second turn returned an empty response"
    assert r2.chat_id == r1.chat_id, f"chat_id changed across turns: {r1.chat_id} -> {r2.chat_id}"


async def list_conversations(ctx: Context) -> None:
    result = await ctx.client.chat.list()
    assert isinstance(result.conversations, list), "conversations is not a list"
    assert len(result.conversations) >= 1, "no conversations listed despite earlier chat checks"


async def get_conversation(ctx: Context) -> None:
    chat_id = ctx.shared["chat_id"]
    conversation = await ctx.client.chat.get(chat_id)
    assert conversation.chat_id == chat_id
    assert isinstance(conversation.messages, list)
    assert len(conversation.messages) >= 1, "conversation has no messages"


async def delete_conversation(ctx: Context) -> None:
    response = await ctx.client.chat.create(message="Test message for delete.")
    assert response.chat_id, "setup chat returned no chat_id"
    result = await ctx.client.chat.delete(response.chat_id)
    assert result is True, "deleting an existing conversation returned False"


CHECKS = [
    Check("chat.create_nonstream", create_nonstream),
    Check("chat.create_stream", create_stream),
    Check("chat.stream_context_manager", stream_context_manager),
    Check("chat.multi_turn", multi_turn),
    Check("chat.list", list_conversations, requires=["chat.create_nonstream"]),
    Check("chat.get", get_conversation, requires=["chat.create_nonstream"]),
    Check("chat.delete", delete_conversation),
]
