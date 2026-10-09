import pytest
from fastapi import HTTPException

from api.files import _validate_iso_timestamp


@pytest.mark.parametrize(
    "value",
    [
        None,
        "2024-01-01",
        "2024-01-01T00:00",
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00.000Z",
        "2024-01-31T23:59:59.999+05:30",
    ],
)
def test_accepts_extended_iso_forms(value):
    _validate_iso_timestamp(value, "created_after")


@pytest.mark.parametrize(
    "value",
    [
        "20240101",
        "20240101T000000",
        "2024-01-01T000000",
        "2024-13-01",
        "not-a-date",
        "",
    ],
)
def test_rejects_basic_and_invalid_forms(value):
    with pytest.raises(HTTPException) as exc:
        _validate_iso_timestamp(value, "created_after")
    assert exc.value.status_code == 422
    assert "created_after" in exc.value.detail
