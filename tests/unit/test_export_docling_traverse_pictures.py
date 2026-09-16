"""Export DoclingDocument must not drop OCR text nested under a picture.

Scanned/image pages come back from Docling with their OCR text attached as
children of a PictureItem rather than to the document body. `export_to_markdown`
skips picture children unless `traverse_pictures=True`, so without it the
component emits a bare `<!-- image -->` and every OCR'd word is lost.

The component imports `lfx` (Langflow) and docling-core, neither of which is in
the backend venv, so these tests skip there and run wherever those are present
(the Langflow image). The pure signature-probe test always runs.
"""

import importlib.util
import inspect
import sys
import types
from pathlib import Path

import pytest

COMPONENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "openrag"
    / "export_docling_document.py"
)


def _load_component_module():
    """Import the component with `lfx` stubbed out, since Langflow isn't installed."""
    if "lfx" not in sys.modules:
        for name in (
            "lfx",
            "lfx.base",
            "lfx.base.data",
            "lfx.base.data.docling_utils",
            "lfx.custom",
            "lfx.io",
            "lfx.schema",
        ):
            sys.modules.setdefault(name, types.ModuleType(name))
        sys.modules["lfx.base.data.docling_utils"].coerce_docling_document = lambda *a, **k: None
        sys.modules["lfx.base.data.docling_utils"].extract_docling_documents = lambda *a, **k: ([], None)
        sys.modules["lfx.base.data.docling_utils"].get_docling_image_ref_mode = lambda *a, **k: None
        sys.modules["lfx.custom"].Component = object
        for io_name in ("DropdownInput", "HandleInput", "MessageTextInput", "Output", "StrInput"):
            setattr(sys.modules["lfx.io"], io_name, lambda *a, **k: None)
        sys.modules["lfx.schema"].Data = object
        sys.modules["lfx.schema"].DataFrame = object

    spec = importlib.util.spec_from_file_location("export_docling_document", COMPONENT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scanned_page_document():
    """A page whose OCR text hangs off a PictureItem, as Docling emits for scans."""
    body_texts = ["3. Leave Entitlements:"]
    picture_texts = [
        "Earned Leave (EL): 18 days annually.",
        "Sick Leave (SL): 12 days per year.",
    ]

    def text_item(index, text, parent):
        return {
            "self_ref": f"#/texts/{index}",
            "parent": {"cref": parent},
            "children": [],
            "content_layer": "body",
            "label": "text",
            "prov": [
                {
                    "page_no": 1,
                    "bbox": {"l": 38, "t": 800, "r": 420, "b": 790, "coord_origin": "BOTTOMLEFT"},
                    "charspan": [0, len(text)],
                }
            ],
            "orig": text,
            "text": text,
        }

    texts = [text_item(0, body_texts[0], "#/body")]
    texts += [text_item(i + 1, t, "#/pictures/0") for i, t in enumerate(picture_texts)]

    return {
        "schema_name": "DoclingDocument",
        "version": "1.10.0",
        "name": "scan",
        "origin": {"mimetype": "application/pdf", "binary_hash": 1, "filename": "scan.pdf", "uri": None},
        "furniture": {
            "self_ref": "#/furniture", "parent": None, "children": [],
            "content_layer": "furniture", "name": "_root_", "label": "unspecified",
        },
        "body": {
            "self_ref": "#/body", "parent": None,
            "children": [{"cref": "#/texts/0"}, {"cref": "#/pictures/0"}],
            "content_layer": "body", "name": "_root_", "label": "unspecified",
        },
        "groups": [],
        "texts": texts,
        "pictures": [
            {
                "self_ref": "#/pictures/0", "parent": {"cref": "#/body"},
                "children": [{"cref": f"#/texts/{i + 1}"} for i in range(len(picture_texts))],
                "content_layer": "body", "label": "picture",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {"l": 71, "t": 770, "r": 523, "b": 473, "coord_origin": "BOTTOMLEFT"},
                        "charspan": [0, 0],
                    }
                ],
                "captions": [], "references": [], "footnotes": [], "annotations": [],
            }
        ],
        "tables": [], "key_value_items": [], "form_items": [],
        "pages": {"1": {"size": {"width": 595.2, "height": 841.92}, "image": None, "page_no": 1}},
    }


def test_traverse_pictures_requested_when_supported():
    """The probe asks for traverse_pictures on a version that accepts it."""
    module = _load_component_module()

    def supports(traverse_pictures=False):
        return None

    assert module.traverse_pictures_kwargs(supports) == {"traverse_pictures": True}


def test_traverse_pictures_omitted_when_unsupported():
    """Older docling-core lacks the parameter; passing it would raise TypeError."""
    module = _load_component_module()

    def no_support(image_mode=None):
        return None

    assert module.traverse_pictures_kwargs(no_support) == {}


def test_markdown_export_keeps_text_nested_under_a_picture():
    """The real defect: OCR text under a PictureItem must survive the export."""
    pytest.importorskip("docling_core")
    from docling_core.types.doc.document import DoclingDocument

    module = _load_component_module()
    doc = DoclingDocument.model_validate(_scanned_page_document())

    exported = doc.export_to_markdown(**module.traverse_pictures_kwargs(doc.export_to_markdown))

    assert "Earned Leave (EL): 18 days annually." in exported
    assert "Sick Leave (SL): 12 days per year." in exported


def test_component_source_requests_traverse_pictures_at_every_call_site():
    """Every export_to_markdown call must opt in, including the fallback paths."""
    source = COMPONENT_PATH.read_text()

    assert source.count("export_to_markdown(") == 4
    assert source.count("traverse_pictures_kwargs(") == 5  # 1 definition + 4 call sites


def test_flow_embeds_the_same_component_source():
    """Langflow runs the copy stored in the flow, so it must not drift from the file."""
    import json

    flow = json.loads(
        (Path(__file__).resolve().parents[2] / "flows" / "ingestion_flow.json").read_text()
    )
    embedded = next(
        node["data"]["node"]["template"]["code"]["value"]
        for node in flow["data"]["nodes"]
        if node["data"]["id"] == "ExportDoclingDocument-zZdRg"
    )

    assert embedded == COMPONENT_PATH.read_text()


def test_signature_probe_tolerates_builtins():
    """inspect.signature raises on some callables; the probe must not blow up."""
    module = _load_component_module()

    try:
        inspect.signature(len)
    except (TypeError, ValueError):
        assert module.traverse_pictures_kwargs(len) == {}
