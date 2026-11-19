import pytest

from utils.dataset_selection import effective_ids, normalize_selection, resolve_v1_selection


@pytest.mark.parametrize("value", [None, "*", ["*"], ["a", "*"]])
def test_all_forms_mean_every_visible_dataset(value):
    assert normalize_selection(value) is None


def test_empty_list_means_none_not_all():
    assert normalize_selection([]) == []


def test_list_is_deduplicated_in_order():
    assert normalize_selection(["b", "a", "b"]) == ["b", "a"]


@pytest.mark.parametrize("value", ["abc", 3, {"a": 1}, [1], [""], ["a", None], True])
def test_malformed_selection_is_rejected_never_widened(value):
    with pytest.raises(ValueError):
        normalize_selection(value)


def _resolve(**kwargs):
    base = {
        "body_has_datasets": False,
        "body_datasets": None,
        "inline_filters": None,
        "saved_filters": None,
    }
    return resolve_v1_selection(**{**base, **kwargs})


def test_nothing_given_selects_all():
    assert _resolve() is None


def test_saved_filter_applies_when_nothing_else_does():
    assert _resolve(saved_filters={"datasets": ["s"]}) == ["s"]


def test_inline_filters_beat_saved_filter():
    assert _resolve(inline_filters={"datasets": ["i"]}, saved_filters={"datasets": ["s"]}) == ["i"]


def test_body_field_beats_inline_and_saved():
    selection = _resolve(
        body_has_datasets=True,
        body_datasets=["b"],
        inline_filters={"datasets": ["i"]},
        saved_filters={"datasets": ["s"]},
    )
    assert selection == ["b"]


def test_empty_list_at_each_level_overrides_lower_levels():
    assert (
        _resolve(body_has_datasets=True, body_datasets=[], inline_filters={"datasets": ["i"]}) == []
    )
    assert _resolve(inline_filters={"datasets": []}, saved_filters={"datasets": ["s"]}) == []
    assert _resolve(saved_filters={"datasets": []}) == []


def test_star_at_a_higher_level_overrides_a_narrower_saved_filter():
    assert (
        _resolve(body_has_datasets=True, body_datasets="*", saved_filters={"datasets": ["s"]})
        is None
    )
    assert _resolve(inline_filters={"datasets": ["*"]}, saved_filters={"datasets": ["s"]}) is None


def test_inline_filters_without_the_key_fall_through_to_saved():
    assert _resolve(inline_filters={"owners": ["x"]}, saved_filters={"datasets": ["s"]}) == ["s"]


def test_malformed_value_at_the_winning_level_raises():
    with pytest.raises(ValueError):
        _resolve(body_has_datasets=True, body_datasets="nope")


def test_effective_ids_is_visibility_intersected_with_selection():
    assert effective_ids(None, ["a", "b"]) == ["a", "b"]
    assert effective_ids(["b", "z"], ["a", "b"]) == ["b"]
    assert effective_ids([], ["a", "b"]) == []


def test_tool_arguments_only_narrow():
    assert effective_ids(["a", "b"], ["a", "b", "c"], ["b", "c"]) == ["b"]
    assert effective_ids(["a"], ["a", "b"], ["b"]) == []
    assert effective_ids(None, ["a", "b"], ["a"]) == ["a"]
    assert effective_ids(None, ["a", "b"], []) == []
    assert effective_ids(None, ["a", "b"], ["*"]) == ["a", "b"]


def test_unusable_tool_argument_narrows_to_nothing():
    assert effective_ids(None, ["a"], [1]) == []  # type: ignore[list-item]
