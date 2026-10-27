"""The ingest flow's Split Text component never returns a chunk over chunk_size.

Docling joins consecutive lines that have no blank line between them into one
Markdown paragraph, so a plain-text file with one sentence per line reaches the
splitter as a few huge newline-free paragraphs. Langflow's built-in Split Text
only cuts on its separator, and kept each such paragraph as a single chunk of
hundreds of thousands of characters.
"""

import hashlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from langchain_core.documents import Document

BUNDLE = Path("custom_components/openrag")
SOURCE = BUNDLE / "split_text.py"
NODE_TYPE = "ext:openrag:OpenRAGSplitTextComponent@extra"
FLOWS_WITH_SPLITTER = ("ingestion_flow.json", "openrag_url_mcp.json")


class FakeData:
    def __init__(self, text: str = "", data: dict | None = None) -> None:
        self.text = text
        self.data = data or {}
        self.text_key = "text"

    def to_lc_document(self) -> Document:
        return Document(page_content=self.text, metadata=dict(self.data))


class FakeInput:
    def __init__(self, **kwargs: object) -> None:
        self.name = kwargs.get("name")


@pytest.fixture
def component_module(monkeypatch: pytest.MonkeyPatch):
    modules = {
        name: ModuleType(name)
        for name in (
            "lfx",
            "lfx.custom",
            "lfx.custom.custom_component",
            "lfx.custom.custom_component.component",
            "lfx.io",
            "lfx.schema",
            "lfx.schema.data",
            "lfx.schema.dataframe",
            "lfx.schema.message",
            "lfx.utils",
            "lfx.utils.util",
        )
    }
    vars(modules["lfx.custom.custom_component.component"])["Component"] = object
    for input_name in (
        "BoolInput",
        "DropdownInput",
        "HandleInput",
        "IntInput",
        "MessageTextInput",
        "Output",
    ):
        setattr(modules["lfx.io"], input_name, FakeInput)
    vars(modules["lfx.schema.data"])["Data"] = FakeData
    vars(modules["lfx.schema.dataframe"])["DataFrame"] = type("DataFrame", (), {})
    vars(modules["lfx.schema.message"])["Message"] = type("Message", (), {})
    vars(modules["lfx.utils.util"])["unescape_string"] = lambda s: s.replace("\\n", "\n")
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_name = "custom_components.openrag.split_text"
    sys.modules.pop(module_name, None)
    yield importlib.import_module(module_name)
    sys.modules.pop(module_name, None)


def _split(module, text: str, *, chunk_size=1000, chunk_overlap=200, separator="\\n"):
    component = module.OpenRAGSplitTextComponent()
    component.data_inputs = [FakeData(text, {"filename": "wiki.txt"})]
    component.chunk_size = chunk_size
    component.chunk_overlap = chunk_overlap
    component.separator = separator
    component.text_key = "text"
    component.keep_separator = "False"
    return component.split_text_base()


def _sentences(count: int) -> list[str]:
    return [f"東京は日本の首都であり、第{i}番目の文はここで終わる。" for i in range(count)]


def test_newline_free_paragraph_is_split_to_chunk_size(component_module):
    sentences = _sentences(5000)
    text = " ".join(sentences)
    assert "\n" not in text

    docs = _split(component_module, text)

    assert len(docs) > 1
    assert max(len(doc.page_content) for doc in docs) <= 1000
    joined = "\n".join(doc.page_content for doc in docs)
    # With Keep Separator off, a "。" that falls on a chunk boundary is dropped.
    assert all(sentence.rstrip("。") in joined for sentence in sentences)
    assert all(doc.metadata == {"filename": "wiki.txt"} for doc in docs)


def test_single_long_line_among_short_lines_is_split(component_module):
    long_line = "x" * 5000
    text = "\n".join(["short line one", long_line, "short line two"])

    docs = _split(component_module, text)

    assert max(len(doc.page_content) for doc in docs) <= 1000
    assert sum(doc.page_content.count("x") for doc in docs) >= 5000


def test_configured_separator_is_still_preferred(component_module):
    lines = [f"line {i:03d} " + "y" * 80 for i in range(40)]

    docs = _split(component_module, "\n".join(lines))

    for doc in docs:
        assert all(part in lines for part in doc.page_content.split("\n"))


def test_separators_try_the_configured_one_first_without_duplicates(component_module):
    separators = component_module.build_separators("\n")

    assert separators[0] == "\n"
    assert separators[-1] == ""
    assert len(separators) == len(set(separators))
    assert "。" in separators


def test_component_type_differs_from_langflow_builtin():
    """Restricted Langflow swaps drifted code of a known built-in type for its own copy."""
    source = SOURCE.read_text(encoding="utf-8")
    assert f'name = "{NODE_TYPE}"' in source
    assert 'display_name: str = "Split Text"' in source


@pytest.mark.parametrize("flow_name", FLOWS_WITH_SPLITTER)
def test_flows_embed_the_openrag_split_text_component(flow_name):
    source = SOURCE.read_text(encoding="utf-8")
    expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    flow = json.loads((Path("flows") / flow_name).read_text(encoding="utf-8"))
    nodes = flow["data"]["nodes"]

    assert not [n for n in nodes if n["data"].get("type") == "SplitText"]
    splitters = [n for n in nodes if n["data"].get("type") == NODE_TYPE]
    assert len(splitters) == 1
    component = splitters[0]["data"]["node"]
    # flows_service and the ingest tweaks find this node by display name
    assert component["display_name"] == "Split Text"
    assert component["template"]["code"]["value"] == source
    assert component["metadata"]["code_hash"] == expected_hash

    node_id = splitters[0]["id"]
    for edge in flow["data"]["edges"]:
        if edge["source"] == node_id:
            assert edge["data"]["sourceHandle"]["dataType"] == NODE_TYPE
            assert "œdataTypeœ:œSplitTextœ" not in edge["sourceHandle"]
