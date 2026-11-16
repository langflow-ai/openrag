"""Environment the TUI hands to the docling-serve process it launches."""

from tui.managers.docling_manager import docling_serve_env


def test_allows_custom_ocr_config():
    """Without this flag docling-serve fails every task that sets an easyocr threshold."""
    env = docling_serve_env({})

    assert env["DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG"] == "true"


def test_keeps_existing_defaults():
    env = docling_serve_env({})

    assert env["DOCLING_SERVE_ALLOW_CUSTOM_VLM_CONFIG"] == "true"
    assert env["DOCLING_SERVE_ENABLE_REMOTE_SERVICES"] == "true"
    assert env["TORCH_COMPILE_DISABLE"] == "1"


def test_operator_values_win():
    env = docling_serve_env({"DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG": "false"})

    assert env["DOCLING_SERVE_ALLOW_CUSTOM_OCR_CONFIG"] == "false"


def test_does_not_mutate_base():
    base = {"PATH": "/bin"}

    docling_serve_env(base)

    assert base == {"PATH": "/bin"}
