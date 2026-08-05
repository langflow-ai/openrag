from types import SimpleNamespace

import pytest

from agent import _extract_delta_text, async_response


class BrokenOutputTextResponse:
    id = "non-stream-response"
    error = None

    @property
    def output_text(self):
        raise TypeError("'NoneType' object is not iterable")


class Chunk(SimpleNamespace):
    def model_dump(self):
        return self.__dict__


class AsyncChunkStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeResponses:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs["stream"]:
            return BrokenOutputTextResponse()

        return AsyncChunkStream(
            [
                Chunk(type="response.output_text.delta", delta={"content": "Hello"}),
                Chunk(type="response.output_text.delta", delta={"content": " world"}),
                Chunk(
                    type="response.completed",
                    response={"id": "stream-response", "output": None},
                ),
            ]
        )


class FakeClient:
    default_headers: dict[str, str] = {}
    api_key = "test-key"

    def __init__(self):
        self.responses = FakeResponses()


def test_extract_delta_text_handles_dict_deltas_without_stringifying_empty_values():
    assert _extract_delta_text({"content": "hello"}) == "hello"
    assert _extract_delta_text({"text": "hello"}) == "hello"
    assert _extract_delta_text({"content": ""}) == ""


@pytest.mark.asyncio
async def test_async_response_falls_back_to_stream_when_output_text_is_unavailable():
    client = FakeClient()

    response_text, response_id, response_obj = await async_response(
        client,
        prompt="",
        model="flow-id",
    )

    assert response_text == "Hello world"
    assert response_id == "stream-response"
    assert response_obj == {"id": "stream-response", "output": None}
    assert [call["stream"] for call in client.responses.calls] == [False, True]
