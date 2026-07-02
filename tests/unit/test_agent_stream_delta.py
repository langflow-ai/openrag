import warnings

from pydantic import BaseModel


class FakeTextDeltaEvent(BaseModel):
    """Mirrors openai's ResponseTextDeltaEvent: `delta` is declared as `str`."""

    delta: str
    type: str


def test_model_dump_excluding_delta_avoids_warning_and_preserves_dict_shape() -> None:
    chunk = FakeTextDeltaEvent.model_construct(
        delta={"content": "Hello"}, type="response.output_text.delta"
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error")

        chunk_data = chunk.model_dump(exclude={"delta"})
        chunk_data["delta"] = chunk.delta

    assert chunk_data["delta"] == {"content": "Hello"}
    assert chunk_data["type"] == "response.output_text.delta"
