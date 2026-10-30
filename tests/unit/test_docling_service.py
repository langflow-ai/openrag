"""
Unit tests for services/docling_service.py
Validates async conversion logic, polling behavior, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.docling_service import (
    PASSWORD_PROTECTED_PDF_DETAIL,
    DoclingPayloadTooLarge,
    DoclingServeError,
    DoclingService,
    is_encrypted_pdf,
    password_protected_pdf_error,
)
from utils.upload_limits import UploadTooLarge

# Shape of a /v1/result body for a password-protected PDF: the task ran to
# completion, but the conversion failed and no document was exported.
_PASSWORD_PROTECTED_RESULT = {
    "status": "failure",
    "errors": [
        {
            "component_type": "user_input",
            "module_name": "",
            "error_message": (
                "docling-parse could not load document abc123: "
                "Failed to load document (PDFium: Incorrect password error)."
            ),
        }
    ],
    "document": {"filename": "secret.pdf", "json_content": None},
}


def _make_response(status_code: int, json_data: dict = None) -> MagicMock:
    """Create a mock HTTP response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}

    # Mock raise_for_status to raise if status_code >= 400
    if status_code >= 400:

        def raise_status():
            raise httpx.HTTPStatusError("Error", request=MagicMock(), response=resp)

        resp.raise_for_status.side_effect = raise_status
    else:
        resp.raise_for_status.return_value = None

    return resp


@pytest.fixture
def mock_httpx_client():
    """Provide a mocked httpx AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    # Mock __aenter__ and __aexit__ for 'async with client' support
    client.__aenter__.return_value = client
    return client


@pytest.fixture
def docling_service(mock_httpx_client):
    """Provide a DoclingService instance with a mocked client."""
    return DoclingService(docling_url="http://docling:8000", httpx_client=mock_httpx_client)


@pytest.fixture(autouse=True)
def no_sleep():
    """Patch asyncio.sleep so tests run instantly."""
    with patch("services.docling_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep


# ── Polling Logic ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_result_success(docling_service, mock_httpx_client):
    """Returns json_content when Docling returns 'success'."""
    # First call: status poll -> success
    # Second call: get result -> document data
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {"json_content": {"key": "value"}}}),
    ]

    result = await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)
    assert result == {"key": "value"}
    assert mock_httpx_client.get.call_count == 2
    # Verify URLs
    calls = mock_httpx_client.get.call_args_list
    assert calls[0].args[0].endswith("/v1/status/poll/task123")
    assert calls[1].args[0].endswith("/v1/result/task123")


@pytest.mark.asyncio
async def test_poll_result_waits_for_pending(docling_service, mock_httpx_client, no_sleep):
    """Polls multiple times if status is 'pending' before succeeding."""
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "pending"}),
        _make_response(200, {"task_status": "pending"}),
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {"json_content": {"key": "value"}}}),
    ]

    result = await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)
    assert result == {"key": "value"}
    assert mock_httpx_client.get.call_count == 4
    assert no_sleep.call_count == 2


@pytest.mark.asyncio
async def test_poll_result_failure_status(docling_service, mock_httpx_client):
    """Raises DoclingServeError when status is 'failure'."""
    mock_httpx_client.get.return_value = _make_response(200, {"task_status": "failure"})

    with pytest.raises(DoclingServeError, match="Docling processing failed"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)


@pytest.mark.asyncio
async def test_poll_result_timeout(docling_service, mock_httpx_client, no_sleep):
    """Raises TimeoutError when task stays pending beyond timeout."""
    mock_httpx_client.get.return_value = _make_response(200, {"task_status": "pending"})

    # timeout=2.0, interval=1.0 -> loop runs at T=0, T=1, exits at T=2
    with pytest.raises(TimeoutError, match="did not complete within"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 2.0)

    assert mock_httpx_client.get.call_count == 2
    assert no_sleep.call_count == 2


@pytest.mark.asyncio
async def test_poll_result_missing_content(docling_service, mock_httpx_client):
    """Raises DoclingServeError if result response is missing json_content."""
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "success"}),
        _make_response(200, {"document": {}}),  # No json_content
    ]

    with pytest.raises(DoclingServeError, match="missing document.json_content"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)


@pytest.mark.asyncio
async def test_poll_result_surfaces_conversion_failure_from_result_payload(
    docling_service, mock_httpx_client
):
    """A 'success' task whose *conversion* failed reports the real cause.

    docling-serve marks the task successful once the job ran; a password-protected
    PDF then yields a result body with status="failure", an errors list and a null
    json_content. The errors must win over the generic "missing json_content".
    """
    mock_httpx_client.get.side_effect = [
        _make_response(200, {"task_status": "success"}),
        _make_response(200, _PASSWORD_PROTECTED_RESULT),
    ]

    with pytest.raises(DoclingServeError) as exc_info:
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)

    message = str(exc_info.value)
    assert message.startswith("Docling processing failed: ")
    assert "Incorrect password" in message
    assert "missing document.json_content" not in message


# ── Password-protected PDFs on newer docling ───────────────────────

# docling >= 2.141 loads through docling-parse first, whose load failure no longer
# names the reason (seen on CPD, tracker #99817).
_DOCLING_PARSE_LOAD_FAILURE = (
    "Docling processing failed: docling-parse could not load document 8fc525: "
    "Failed to load document with key key=8fc525"
)
_XREF_TABLE = b"xref\n0 1\n0000000000 65535 f \n"


def _pdf(body: bytes, trailer: bytes, *, junk: bytes = b"") -> bytes:
    """Minimal classic-xref PDF; with ``junk``, offsets are relative to the header."""
    head = b"%PDF-1.7\n" + body
    return junk + head + _XREF_TABLE + trailer + b"\nstartxref\n%d\n%%%%EOF\n" % len(head)


def _append_revision(pdf: bytes, body: bytes, trailer: bytes) -> bytes:
    """Append an incremental update whose trailer becomes the active one."""
    head = pdf + body
    return head + _XREF_TABLE + trailer + b"\nstartxref\n%d\n%%%%EOF\n" % len(head)


def _xref_stream_pdf(entries: bytes, data: bytes) -> bytes:
    """Minimal PDF whose active cross-reference section is an xref stream."""
    head = b"%PDF-1.5\n"
    xref = b"9 0 obj\n<< /Type /XRef %s /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (
        entries,
        len(data),
        data,
    )
    return head + xref + b"startxref\n%d\n%%%%EOF\n" % len(head)


def _stale_startxref_pdf(objects: bytes) -> bytes:
    """PDF whose ``startxref`` names the first of ``objects`` rather than an xref section."""
    head = b"%PDF-1.5\n"
    return head + objects + b"startxref\n%d\n%%%%EOF\n" % len(head)


_CATALOG = b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
_ENCRYPTED_PDF = _pdf(_CATALOG, b"trailer\n<< /Root 1 0 R /Encrypt 5 0 R /Size 6 >>")
_PLAIN_PDF = _pdf(_CATALOG, b"trailer\n<< /Root 1 0 R >>")
# Unencrypted, but a content stream shows the literal text "/Encrypt 1 0 R".
_PLAIN_PDF_WITH_ENCRYPT_TEXT = _pdf(
    _CATALOG + b"4 0 obj\n<< /Length 25 >>\nstream\nBT (/Encrypt 1 0 R) Tj ET\nendstream\nendobj\n",
    b"trailer\n<< /Root 1 0 R >>",
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(_ENCRYPTED_PDF, True, id="classic-trailer-encrypted"),
        pytest.param(
            _xref_stream_pdf(b"/Encrypt << /Filter /Standard >>", b"abc"),
            True,
            id="xref-stream-encrypted",
        ),
        pytest.param(
            _append_revision(
                _ENCRYPTED_PDF,
                b"2 0 obj\n<< /Type /Page >>\nendobj\n",
                b"trailer\n<< /Root 1 0 R /Prev %d /Encrypt 5 0 R /Size 6 >>"
                % _ENCRYPTED_PDF.index(b"xref"),
            ),
            True,
            id="incremental-update-encrypted",
        ),
        pytest.param(
            _pdf(_CATALOG, b"trailer\n<< /Root 1 0 R /Encrypt 5 0 R >>", junk=b"JUNK\n"),
            True,
            id="junk-before-header",
        ),
        pytest.param(_PLAIN_PDF, False, id="classic-trailer-plain"),
        pytest.param(_PLAIN_PDF_WITH_ENCRYPT_TEXT, False, id="encrypt-in-content-stream"),
        pytest.param(
            _xref_stream_pdf(b"", b"/Encrypt 1 0 R"), False, id="encrypt-in-xref-stream-data"
        ),
        pytest.param(
            b"%PDF-1.7\n" + _CATALOG + b"trailer\n<< /Root 1 0 R /Encrypt 5 0 R >>\n",
            False,
            id="truncated-no-startxref",
        ),
        pytest.param(
            b"%PDF-1.7\ntrailer\n<< /Encrypt 5 0 R >>\nstartxref\n3\n%%EOF\n",
            False,
            id="startxref-points-at-garbage",
        ),
        pytest.param(
            _stale_startxref_pdf(b"3 0 obj\n<< /Type /Filespec /Encrypt 5 0 R >>\nendobj\n"),
            False,
            id="startxref-points-at-non-xref-object",
        ),
        pytest.param(
            # The non-xref dictionary ends at `endobj`; the later xref stream's
            # /Type /XRef and /Encrypt must not be read as belonging to it.
            _stale_startxref_pdf(
                b"3 0 obj\n<< /Type /Filespec >>\nendobj\n"
                b"9 0 obj\n<< /Type /XRef /Encrypt 5 0 R /Length 3 >>\nstream\nabc\n"
                b"endstream\nendobj\n"
            ),
            False,
            id="startxref-points-at-object-before-xref-stream",
        ),
        pytest.param(
            # Offsets are relative to the header, as in the classic junk case.
            b"JUNK\n" + _xref_stream_pdf(b"/Encrypt 5 0 R", b"abc"),
            True,
            id="xref-stream-junk-before-header",
        ),
        pytest.param(b"not a pdf /Encrypt 5 0 R startxref 0", False, id="not-a-pdf"),
    ],
)
def test_is_encrypted_pdf(content, expected):
    assert is_encrypted_pdf(content) is expected


def test_password_protected_pdf_error_needs_load_failure_and_encryption():
    assert (
        password_protected_pdf_error(_DOCLING_PARSE_LOAD_FAILURE, _ENCRYPTED_PDF)
        == PASSWORD_PROTECTED_PDF_DETAIL
    )
    # A corrupt but unencrypted PDF keeps docling's own message.
    assert password_protected_pdf_error(_DOCLING_PARSE_LOAD_FAILURE, _PLAIN_PDF) is None
    # An owner-password-only PDF that failed for another reason is not relabelled.
    assert (
        password_protected_pdf_error("Docling processing failed: OCR crashed", _ENCRYPTED_PDF)
        is None
    )


@pytest.mark.asyncio
async def test_convert_bytes_names_password_protected_pdf(docling_service):
    with (
        patch.object(
            docling_service, "upload_to_docling_direct_async", AsyncMock(return_value="t1")
        ),
        patch.object(
            docling_service,
            "get_docling_result_async",
            AsyncMock(side_effect=DoclingServeError(_DOCLING_PARSE_LOAD_FAILURE)),
        ),
        pytest.raises(DoclingServeError) as exc_info,
    ):
        await docling_service.convert_bytes(_ENCRYPTED_PDF, "secret.pdf")

    assert str(exc_info.value) == f"Docling processing failed: {PASSWORD_PROTECTED_PDF_DETAIL}"
    assert str(exc_info.value.__cause__) == _DOCLING_PARSE_LOAD_FAILURE


@pytest.mark.asyncio
async def test_convert_bytes_keeps_docling_error_when_encrypt_appears_outside_trailer(
    docling_service,
):
    """Literal /Encrypt text in page content must not relabel an unrelated load failure."""
    with (
        patch.object(
            docling_service, "upload_to_docling_direct_async", AsyncMock(return_value="t1")
        ),
        patch.object(
            docling_service,
            "get_docling_result_async",
            AsyncMock(side_effect=DoclingServeError(_DOCLING_PARSE_LOAD_FAILURE)),
        ),
        pytest.raises(DoclingServeError) as exc_info,
    ):
        await docling_service.convert_bytes(_PLAIN_PDF_WITH_ENCRYPT_TEXT, "about-pdf.pdf")

    assert str(exc_info.value) == _DOCLING_PARSE_LOAD_FAILURE


@pytest.mark.asyncio
async def test_convert_file_keeps_docling_error_for_unencrypted_pdf(docling_service, tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(_PLAIN_PDF)
    with (
        patch.object(
            docling_service, "upload_to_docling_direct_async", AsyncMock(return_value="t1")
        ),
        patch.object(
            docling_service,
            "get_docling_result_async",
            AsyncMock(side_effect=DoclingServeError(_DOCLING_PARSE_LOAD_FAILURE)),
        ),
        pytest.raises(DoclingServeError, match="Failed to load document with key"),
    ):
        await docling_service.convert_file(str(pdf))


@pytest.mark.asyncio
async def test_poll_result_http_error(docling_service, mock_httpx_client):
    """Propagates HTTP errors during polling as DoclingServeError."""
    mock_httpx_client.get.return_value = _make_response(500)

    with pytest.raises(DoclingServeError, match="Error polling docling status"):
        await docling_service._poll_result(mock_httpx_client, "task123", 1.0, 10.0)


# ── Upload Logic ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_success(docling_service, mock_httpx_client):
    """Returns task_id on successful upload."""
    mock_httpx_client.post.return_value = _make_response(200, {"task_id": "new-task-id"})

    # Mock config to avoid missing attribute errors during _build_docling_options
    with patch("services.docling_service.get_openrag_config") as mock_get_config:
        mock_config = MagicMock()
        mock_config.knowledge.table_structure = False
        mock_config.knowledge.ocr = False
        mock_config.knowledge.picture_descriptions = False
        mock_config.knowledge.vlm_enabled = False
        mock_get_config.return_value = mock_config

        task_id = await docling_service.upload_to_docling_direct_async("test.pdf", b"data")

    assert task_id == "new-task-id"
    assert mock_httpx_client.post.call_count == 1

    # Verify boolean serialization (bool -> "true"/"false")
    _, kwargs = mock_httpx_client.post.call_args
    data = kwargs.get("data", {})
    assert data["do_ocr"] == "false"


@pytest.mark.asyncio
async def test_upload_http_error(docling_service, mock_httpx_client):
    """Raises exception if upload returns non-200."""
    mock_httpx_client.post.return_value = _make_response(400)

    with patch("services.docling_service.get_openrag_config") as mock_get_config:
        mock_config = MagicMock()
        mock_config.knowledge.table_structure = False
        mock_config.knowledge.ocr = False
        mock_config.knowledge.picture_descriptions = False
        mock_config.knowledge.vlm_enabled = False
        mock_get_config.return_value = mock_config

        with pytest.raises(httpx.HTTPStatusError):
            await docling_service.upload_to_docling_direct_async("test.pdf", b"data")


@pytest.mark.asyncio
async def test_upload_refuses_before_posting_when_over_the_limit(
    docling_service, mock_httpx_client, monkeypatch
):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)

    with pytest.raises(UploadTooLarge, match="big.pdf"):
        await docling_service.upload_to_docling_direct_async("big.pdf", b"x" * (1024 * 1024 + 1))

    mock_httpx_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_upload_maps_docling_proxy_413(docling_service, mock_httpx_client):
    """A 413 from the proxy becomes a message that names the file and the fix."""
    mock_httpx_client.post.return_value = _make_response(413)

    with patch("services.docling_service.get_openrag_config") as mock_get_config:
        mock_config = MagicMock()
        mock_config.knowledge.table_structure = False
        mock_config.knowledge.ocr = False
        mock_config.knowledge.picture_descriptions = False
        mock_config.knowledge.vlm_enabled = False
        mock_get_config.return_value = mock_config

        with (
            patch("services.docling_service.logger") as mock_logger,
            pytest.raises(DoclingPayloadTooLarge, match="report.pdf") as exc_info,
        ):
            await docling_service.upload_to_docling_direct_async("report.pdf", b"data")

    message = str(exc_info.value)
    assert "document-processing service" in message
    assert "within the configured upload limit" in message
    assert "OPENRAG_MAX_UPLOAD_MB" in message
    assert "http://docling:8000" not in message
    assert "client_max_body_size" not in message
    logged = mock_logger.error.call_args.kwargs["error"]
    assert "http://docling:8000/v1/convert/file/async" in logged
    assert "client_max_body_size" in logged


# ── Configuration Logic ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_docling_options_toggles(docling_service):
    """Correctly maps OpenRAG config to Docling options."""
    mock_config = MagicMock()
    mock_config.knowledge.table_structure = True
    mock_config.knowledge.ocr = True
    mock_config.knowledge.picture_descriptions = False
    mock_config.knowledge.vlm_enabled = False

    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    assert options["do_table_structure"] is True
    assert options["do_ocr"] is True
    assert options["do_picture_description"] is False
    assert options["to_formats"] == "json"
    assert options["image_export_mode"] == "placeholder"
    assert "include_page_images" not in options
    assert "include_images" not in options


@pytest.mark.asyncio
async def test_build_docling_options_preview_mode_embeds_page_images(docling_service):
    """Preview mode requests embedded page rasters for PDF bbox overlays."""
    mock_config = MagicMock()
    mock_config.knowledge.table_structure = False
    mock_config.knowledge.ocr = False
    mock_config.knowledge.picture_descriptions = False
    mock_config.knowledge.vlm_enabled = False

    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async(preview_mode=True)

    assert options["to_formats"] == "json"
    assert options["image_export_mode"] == "embedded"
    assert options["include_page_images"] is True
    assert options["include_images"] is True


@pytest.mark.asyncio
async def test_build_docling_options_sends_configured_ocr_languages(docling_service):
    """OCR languages from KnowledgeConfig reach docling as engine-specific codes."""
    mock_config = MagicMock()
    mock_config.knowledge.table_structure = False
    mock_config.knowledge.ocr = True
    mock_config.knowledge.ocr_languages = ["en", "ja"]
    mock_config.knowledge.picture_descriptions = False
    mock_config.knowledge.vlm_enabled = False

    with (
        patch("services.docling_service.get_openrag_config", return_value=mock_config),
        patch("services.docling_service.platform.system", return_value="Darwin"),
    ):
        options = await docling_service._build_docling_options_async()

    assert options["ocr_lang"] == ["ja-JP", "en-US"]


@pytest.mark.asyncio
async def test_upload_sends_ocr_lang_as_repeated_form_fields(docling_service, mock_httpx_client):
    """httpx encodes a list form value as repeated parts; docling needs that shape."""
    mock_config = MagicMock()
    mock_config.knowledge.table_structure = False
    mock_config.knowledge.ocr = True
    mock_config.knowledge.ocr_languages = ["en", "ja"]
    mock_config.knowledge.picture_descriptions = False
    mock_config.knowledge.vlm_enabled = False

    mock_httpx_client.post.return_value = _make_response(200, {"task_id": "t1"})

    with (
        patch("services.docling_service.get_openrag_config", return_value=mock_config),
        patch("services.docling_service.platform.system", return_value="Darwin"),
    ):
        await docling_service.upload_to_docling_direct_async("doc.pdf", b"data")

    sent = mock_httpx_client.post.call_args.kwargs["data"]
    assert sent["ocr_lang"] == ["ja-JP", "en-US"]
    assert sent["ocr_preset"] == "ocrmac"
    assert "ocr_engine" not in sent


def test_preset_configs_macos():
    """Uses ocrmac engine on macOS."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True)
        assert preset["ocr_preset"] == "ocrmac"


def test_preset_configs_linux():
    """Uses easyocr engine on non-macOS."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Linux"):
        preset = get_docling_preset_configs(ocr=True)
        assert preset["ocr_preset"] == "easyocr"


def test_preset_configs_never_sends_deprecated_ocr_engine():
    """Use the supported preset field rather than the deprecated engine field."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=["ja", "en"])

    assert "ocr_engine" not in preset


def test_preset_configs_maps_languages_to_ocrmac_codes():
    """ocrmac wants BCP-47 tags, not the neutral codes stored in config."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=["ja", "en", "vi"])

    assert preset["ocr_lang"] == ["ja-JP", "vi-VN", "en-US"]


def test_preset_configs_maps_languages_to_easyocr_codes():
    """easyocr wants short codes, and its own spelling for Chinese."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Linux"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=["ja", "zh-Hans"])

    assert preset["ocr_lang"] == ["ja", "ch_sim"]


def test_preset_configs_passes_through_unknown_language_codes():
    """An engine code the map does not know is forwarded rather than dropped."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Linux"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=["bn"])

    assert preset["ocr_lang"] == ["bn"]


def test_preset_configs_omits_ocr_lang_when_no_languages_configured():
    """Empty config must not send an empty list that would override engine defaults."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=[])

    assert "ocr_lang" not in preset


def test_init_default_url():
    """Uses DOCLING_SERVE_URL from config.settings if not provided."""
    with patch("services.docling_service.DOCLING_SERVE_URL", "http://default:5001"):
        service = DoclingService()
        assert service.docling_url == "http://default:5001"


# ── VLM Pipeline Options ────────────────────────────────────────────


def _vlm_mock_config(provider: str) -> MagicMock:
    mock_config = MagicMock()
    k = mock_config.knowledge
    k.vlm_enabled = True
    k.vlm_provider = provider
    k.vlm_model = "gpt-4o" if provider == "openai" else "meta-llama/llama-vision"
    k.vlm_prompt = "Extract all text."
    k.vlm_response_format = "markdown"
    k.vlm_max_tokens = 5000
    k.vlm_concurrency = 4
    k.vlm_timeout = 120
    k.vlm_openai_url = "https://api.openai.com/v1/chat/completions"
    k.vlm_watsonx_api_version = "2023-05-29"
    k.table_structure = False
    k.ocr = False
    k.picture_descriptions = True
    mock_config.providers.openai.api_key = "sk-test"
    mock_config.providers.credential_values.return_value = {}
    mock_config.providers.watsonx.api_key = "wx-key"
    mock_config.providers.watsonx.endpoint = "https://us-south.ml.cloud.ibm.com/"
    mock_config.providers.watsonx.project_id = "proj-123"
    return mock_config


@pytest.mark.asyncio
async def test_build_vlm_options_openai(docling_service):
    """OpenAI VLM options carry the provider key and chat-completions params."""
    mock_config = _vlm_mock_config("openai")
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    assert options["do_picture_description"] is True
    assert options["to_formats"] == "json"
    api = options["picture_description_api"]
    assert api["url"] == "https://api.openai.com/v1/chat/completions"
    assert api["headers"]["Authorization"] == "Bearer sk-test"
    assert api["params"] == {"model": "gpt-4o", "max_completion_tokens": 5000}
    assert api["prompt"] == "Extract all text."


@pytest.mark.asyncio
async def test_build_vlm_options_openai_custom_base_url(docling_service):
    """OpenAI VLM requests preserve a configured gateway path prefix."""
    mock_config = _vlm_mock_config("openai")
    mock_config.providers.credential_values.return_value = {
        "api_base": "https://gateway.example/openai"
    }
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    assert (
        options["picture_description_api"]["url"]
        == "https://gateway.example/openai/chat/completions"
    )
    mock_config.providers.credential_values.assert_called_once_with("openai")


@pytest.mark.asyncio
async def test_build_vlm_options_watsonx(docling_service):
    """watsonx VLM options exchange the API key for an IAM bearer token."""
    mock_config = _vlm_mock_config("watsonx")
    with (
        patch("services.docling_service.get_openrag_config", return_value=mock_config),
        patch(
            "enhancements.providers.watsonx.iam.get_iam_token", new_callable=AsyncMock
        ) as mock_token,
    ):
        mock_token.return_value = "iam-token"
        options = await docling_service._build_docling_options_async()

    mock_token.assert_awaited_once_with("wx-key")
    api = options["picture_description_api"]
    assert api["url"] == "https://us-south.ml.cloud.ibm.com/ml/v1/text/chat?version=2023-05-29"
    assert api["headers"]["Authorization"] == "Bearer iam-token"
    assert api["params"] == {
        "model_id": "meta-llama/llama-vision",
        "project_id": "proj-123",
        "max_tokens": 5000,
    }


@pytest.mark.asyncio
async def test_build_vlm_options_watsonx_unconfigured(docling_service):
    """Raises DoclingServeError when watsonx provider is incomplete."""
    mock_config = _vlm_mock_config("watsonx")
    mock_config.providers.watsonx.project_id = ""
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        with pytest.raises(DoclingServeError, match="watsonx provider is not fully"):
            await docling_service._build_docling_options_async()


@pytest.mark.asyncio
async def test_build_vlm_options_ollama(docling_service):
    """Ollama VLM options carry the provider endpoint and chat-completions params."""
    mock_config = _vlm_mock_config("ollama")
    mock_config.providers.ollama.endpoint = "http://localhost:11434"
    mock_config.providers.ollama.configured = True
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    assert options["do_picture_description"] is True
    assert options["to_formats"] == "json"
    api = options["picture_description_api"]
    assert api["url"] == "http://localhost:11434/v1/chat/completions"
    assert api["headers"] == {}
    assert api["params"] == {"model": "meta-llama/llama-vision", "max_completion_tokens": 5000}
    assert api["prompt"] == "Extract all text."


@pytest.mark.asyncio
async def test_build_vlm_options_azure(docling_service):
    """Azure VLM options carry the deployment URL, api-key header, and completion params."""
    mock_config = _vlm_mock_config("azure")
    mock_config.knowledge.vlm_model = "azure/gpt-4.1"
    mock_config.providers.credential_values = lambda provider: {
        "api_key": "azure-key",
        "api_base": "https://example.openai.azure.com",
        "api_version": "2024-02-01",
    }
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    assert options["do_picture_description"] is True
    api = options["picture_description_api"]
    assert (
        api["url"]
        == "https://example.openai.azure.com/openai/deployments/gpt-4.1/chat/completions?api-version=2024-02-01"
    )
    assert api["headers"] == {"api-key": "azure-key"}
    assert api["params"] == {"model": "gpt-4.1", "max_completion_tokens": 5000}
    assert api["prompt"] == "Extract all text."


@pytest.mark.asyncio
async def test_build_vlm_options_azure_rejects_non_https(docling_service):
    """Azure VLM options reject plain HTTP endpoints."""
    mock_config = _vlm_mock_config("azure")
    mock_config.knowledge.vlm_model = "azure/gpt-4.1"
    mock_config.providers.credential_values = lambda provider: {
        "api_key": "azure-key",
        "api_base": "http://example.openai.azure.com",
    }
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        with pytest.raises(DoclingServeError, match="Azure VLM endpoint must use HTTPS"):
            await docling_service._build_docling_options_async()


@pytest.mark.asyncio
async def test_upload_vlm_enabled_sends_vlm_form_fields(docling_service, mock_httpx_client):
    """VLM upload sends custom picture description parameters."""
    import json as json_lib

    mock_httpx_client.post.return_value = _make_response(200, {"task_id": "vlm-task"})
    mock_config = _vlm_mock_config("openai")
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        task_id = await docling_service.upload_to_docling_direct_async("test.pdf", b"data")

    assert task_id == "vlm-task"
    _, kwargs = mock_httpx_client.post.call_args
    data = kwargs.get("data", {})
    assert data["do_picture_description"] == "true"
    api = json_lib.loads(data["picture_description_api"])
    assert api["params"]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_build_vlm_options_azure_ai_foundry(docling_service):
    """Foundry keeps its own endpoint shape instead of falling back to OpenAI.

    `azure_ai` is Azure AI Foundry, not the Azure OpenAI Service: its api_base
    already points at the `/models` route, so chat completions hang directly
    off it rather than under `/openai/deployments/<name>`.
    """
    mock_config = _vlm_mock_config("azure_ai")
    mock_config.knowledge.vlm_model = "azure_ai/mistral-small-2503"
    mock_config.providers.credential_values = lambda provider: {
        "api_key": "foundry-key",
        "api_base": "https://example.services.ai.azure.com/models",
        "api_version": "2024-05-01-preview",
    }
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        options = await docling_service._build_docling_options_async()

    api = options["picture_description_api"]
    assert api["url"] == (
        "https://example.services.ai.azure.com/models/chat/completions"
        "?api-version=2024-05-01-preview"
    )
    assert api["headers"] == {"api-key": "foundry-key"}
    assert api["params"] == {"model": "mistral-small-2503", "max_completion_tokens": 5000}


@pytest.mark.asyncio
async def test_build_vlm_options_azure_ai_requires_credentials(docling_service):
    mock_config = _vlm_mock_config("azure_ai")
    mock_config.providers.credential_values = lambda provider: {}
    with patch("services.docling_service.get_openrag_config", return_value=mock_config):
        with pytest.raises(DoclingServeError, match="Azure AI Foundry provider is not"):
            await docling_service._build_docling_options_async()


def test_docling_config_model_accepts_preset_output():
    """DoclingConfig validates the dict get_docling_preset_configs produces."""
    from services.docling_service import DoclingConfig, get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        preset = get_docling_preset_configs(ocr=True, ocr_languages=["en", "ja"])

    config = DoclingConfig(**preset)

    assert config.ocr_preset == "ocrmac"
    assert config.ocr_lang == ["ja-JP", "en-US"]


def test_preset_configs_maps_arabic_per_engine():
    """Arabic is in the curated set; ocrmac and easyocr spell it differently."""
    from services.docling_service import get_docling_preset_configs

    with patch("services.docling_service.platform.system", return_value="Darwin"):
        mac = get_docling_preset_configs(ocr=True, ocr_languages=["ar"])
    with patch("services.docling_service.platform.system", return_value="Linux"):
        linux = get_docling_preset_configs(ocr=True, ocr_languages=["ar"])

    assert mac["ocr_lang"] == ["ar-SA"]
    assert linux["ocr_lang"] == ["ar"]
