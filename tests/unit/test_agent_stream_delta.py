import warnings

from pydantic import BaseModel


class FakeTextDeltaEvent(BaseModel):
    """Mirrors openai's ResponseTextDeltaEvent: `delta` is declared as `str`."""

    delta: str
    type: str


chunk = FakeTextDeltaEvent.model_construct(
    delta={"content": "Hello"}, type="response.output_text.delta"
)


def test_model_dump_without_exclusion_raises_serialization_warning() -> None:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        chunk.model_dump()

    assert any(
        issubclass(w.category, UserWarning)
        and "PydanticSerializationUnexpectedValue" in str(w.message)
        for w in recorded
    ), "expected a PydanticSerializationUnexpectedValue warning for the delta type mismatch"


def test_model_dump_excluding_delta_avoids_warning_and_preserves_dict_shape() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")

        chunk_data = chunk.model_dump(exclude={"delta"})
        chunk_data["delta"] = chunk.delta

    assert chunk_data["delta"] == {"content": "Hello"}
    assert chunk_data["type"] == "response.output_text.delta"
