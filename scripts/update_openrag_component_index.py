#!/usr/bin/env python3
"""Insert OpenRAG custom components into flows/component_index.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "flows" / "component_index.json"
COMPONENTS_DIR = ROOT / "flows" / "components"
# Langflow uses this string as the sidebar category label.
BUNDLE_NAME = "OpenRAG"


def _code_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _code_field(source: str) -> dict:
    return {
        "advanced": True,
        "api_editable": False,
        "dynamic": True,
        "fileTypes": [],
        "file_path": "",
        "info": "",
        "list": False,
        "load_from_db": False,
        "multiline": True,
        "name": "code",
        "password": False,
        "placeholder": "",
        "required": True,
        "show": True,
        "title_case": False,
        "type": "code",
        "value": source,
    }


def _str_input(
    name: str,
    display_name: str,
    info: str,
    *,
    value: str = "",
    load_from_db: bool = False,
    advanced: bool = False,
) -> dict:
    return {
        "_input_type": "StrInput",
        "advanced": advanced,
        "api_editable": False,
        "display_name": display_name,
        "dynamic": False,
        "info": info,
        "list": False,
        "list_add_label": "Add More",
        "load_from_db": load_from_db,
        "name": name,
        "override_skip": False,
        "placeholder": "",
        "required": False,
        "show": True,
        "title_case": False,
        "tool_mode": False,
        "trace_as_metadata": True,
        "track_in_telemetry": False,
        "type": "str",
        "value": value,
    }


def _secret_input(name: str, display_name: str, info: str, *, value: str) -> dict:
    return {
        "_input_type": "SecretStrInput",
        "advanced": False,
        "api_editable": False,
        "display_name": display_name,
        "dynamic": False,
        "info": info,
        "input_types": [],
        "load_from_db": True,
        "name": name,
        "override_skip": False,
        "password": True,
        "placeholder": "",
        "required": False,
        "show": True,
        "title_case": False,
        "track_in_telemetry": False,
        "type": "str",
        "value": value,
    }


def _int_input(name: str, display_name: str, info: str, *, value="", advanced: bool = True) -> dict:
    return {
        "_input_type": "IntInput",
        "advanced": advanced,
        "api_editable": False,
        "display_name": display_name,
        "dynamic": False,
        "info": info,
        "list": False,
        "list_add_label": "Add More",
        "name": name,
        "override_skip": False,
        "placeholder": "",
        "required": False,
        "show": True,
        "title_case": False,
        "tool_mode": False,
        "trace_as_metadata": True,
        "track_in_telemetry": True,
        "type": "int",
        "value": value,
    }


def _output(display_name: str, method: str, name: str, selected: str) -> dict:
    return {
        "allows_loop": False,
        "cache": True,
        "display_name": display_name,
        "group_outputs": False,
        "method": method,
        "name": name,
        "selected": selected,
        "tool_mode": True,
        "types": [selected],
        "value": "__UNDEFINED__",
    }


def _component(
    *,
    source: str,
    class_name: str,
    display_name: str,
    description: str,
    module: str,
    base_classes: list[str],
    field_order: list[str],
    outputs: list[dict],
    template: dict,
) -> dict:
    template = {"_type": "Component", "code": _code_field(source), **template}
    return {
        "base_classes": base_classes,
        "beta": False,
        "conditional_paths": [],
        "custom_fields": {},
        "description": description,
        "display_name": display_name,
        "documentation": "",
        "edited": False,
        "field_order": field_order,
        "frozen": False,
        "icon": "OpenRAG",
        "legacy": False,
        "metadata": {
            "code_hash": _code_hash(source),
            "dependencies": {
                "dependencies": [{"name": "lfx", "version": None}],
                "total_dependencies": 1,
            },
            "module": module,
        },
        "minimized": False,
        "output_types": [],
        "outputs": outputs,
        "pinned": False,
        "template": template,
        "tool_mode": False,
    }


def llm_component() -> dict:
    source = (COMPONENTS_DIR / "openai_compatible_llm.py").read_text(encoding="utf-8")
    return _component(
        source=source,
        class_name="OpenAICompatibleLLMComponent",
        display_name="OpenRAG LLM",
        description=(
            "Chat model via OpenRAG's OpenAI-compatible /v1 proxy. "
            "Base URL and hop token come from global variables at runtime."
        ),
        module="custom_components.OpenRAG.openai_compatible_llm.OpenAICompatibleLLMComponent",
        base_classes=["LanguageModel", "Message"],
        field_order=[
            "input_value",
            "system_message",
            "stream",
            "model_name",
            "api_key",
            "api_base",
            "temperature",
            "max_tokens",
            "seed",
        ],
        outputs=[
            _output("Model Response", "text_response", "text_output", "Message"),
            _output("Language Model", "build_model", "model_output", "LanguageModel"),
        ],
        template={
            "api_base": _str_input(
                "api_base",
                "OpenAI API Base",
                "Must end with /v1 (for example http://openrag-backend:8000/v1). "
                "Bound to OPENRAG_LLM_BASE_URL at runtime. Same URL as embeddings.",
                value="OPENRAG_LLM_BASE_URL",
                load_from_db=True,
            ),
            "api_key": _secret_input(
                "api_key",
                "OpenRAG LLM Token",
                "Hop token from OPENRAG_LLM_TOKEN. OpenRAG injects this per Langflow run.",
                value="OPENRAG_LLM_TOKEN",
            ),
            "input_value": {
                "_input_type": "MessageInput",
                "advanced": False,
                "api_editable": False,
                "display_name": "Input",
                "dynamic": False,
                "info": "The input text to send to the model",
                "input_types": ["Message"],
                "list": False,
                "list_add_label": "Add More",
                "load_from_db": False,
                "name": "input_value",
                "override_skip": False,
                "placeholder": "",
                "required": False,
                "show": True,
                "title_case": False,
                "tool_mode": False,
                "trace_as_input": True,
                "trace_as_metadata": True,
                "track_in_telemetry": False,
                "type": "str",
                "value": "",
            },
            "max_tokens": _int_input(
                "max_tokens",
                "Max Tokens",
                "Maximum number of tokens to generate. Leave empty for the model default.",
            ),
            "model_name": _str_input(
                "model_name",
                "Model Name",
                "Chat model id. Bound to SELECTED_LANGUAGE_MODEL at runtime.",
                value="SELECTED_LANGUAGE_MODEL",
                load_from_db=True,
            ),
            "seed": _int_input(
                "seed",
                "Seed",
                "The seed controls the reproducibility of the job.",
                value=1,
            ),
            "stream": {
                "_input_type": "BoolInput",
                "advanced": True,
                "api_editable": False,
                "display_name": "Stream",
                "dynamic": False,
                "info": "Whether to stream the response",
                "list": False,
                "list_add_label": "Add More",
                "name": "stream",
                "override_skip": False,
                "placeholder": "",
                "required": False,
                "show": True,
                "title_case": False,
                "tool_mode": False,
                "trace_as_metadata": True,
                "track_in_telemetry": True,
                "type": "bool",
                "value": False,
            },
            "system_message": {
                "_input_type": "MultilineInput",
                "advanced": False,
                "ai_enabled": False,
                "api_editable": False,
                "copy_field": False,
                "display_name": "System Message",
                "dynamic": False,
                "info": "A system message that helps set the behavior of the assistant",
                "input_types": ["Message"],
                "list": False,
                "list_add_label": "Add More",
                "load_from_db": False,
                "multiline": True,
                "name": "system_message",
                "override_skip": False,
                "password": False,
                "placeholder": "",
                "required": False,
                "show": True,
                "title_case": False,
                "tool_mode": False,
                "trace_as_input": True,
                "trace_as_metadata": True,
                "track_in_telemetry": False,
                "type": "str",
                "value": "",
            },
            "temperature": {
                "_input_type": "SliderInput",
                "advanced": True,
                "api_editable": False,
                "display_name": "Temperature",
                "dynamic": False,
                "info": "Controls randomness in responses",
                "max_label": "",
                "max_label_icon": "",
                "min_label": "",
                "min_label_icon": "",
                "name": "temperature",
                "override_skip": False,
                "placeholder": "",
                "range_spec": {"max": 1.0, "min": 0.0, "step": 0.01, "step_type": "float"},
                "required": False,
                "show": True,
                "slider_buttons": False,
                "slider_buttons_options": [],
                "slider_input": False,
                "title_case": False,
                "tool_mode": False,
                "track_in_telemetry": False,
                "type": "slider",
                "value": 0.1,
            },
        },
    )


def embedding_component() -> dict:
    source = (COMPONENTS_DIR / "openai_compatible_embedding.py").read_text(encoding="utf-8")
    return _component(
        source=source,
        class_name="OpenAICompatibleEmbeddingComponent",
        display_name="OpenRAG Embeddings",
        description=(
            "Embeddings via OpenRAG's OpenAI-compatible /v1 proxy. "
            "Uses the same base URL and hop token as the chat component."
        ),
        module="custom_components.OpenRAG.openai_compatible_embedding.OpenAICompatibleEmbeddingComponent",
        base_classes=["Embeddings"],
        field_order=["model_name", "api_key", "api_base", "dimensions", "chunk_size"],
        outputs=[_output("Embedding Model", "build_embeddings", "embeddings", "Embeddings")],
        template={
            "api_base": _str_input(
                "api_base",
                "OpenAI API Base",
                "Must end with /v1 (for example http://openrag-backend:8000/v1). "
                "Bound to OPENRAG_LLM_BASE_URL at runtime. Same URL as chat.",
                value="OPENRAG_LLM_BASE_URL",
                load_from_db=True,
            ),
            "api_key": _secret_input(
                "api_key",
                "OpenRAG LLM Token",
                "Hop token from OPENRAG_LLM_TOKEN. Same token as the chat component.",
                value="OPENRAG_LLM_TOKEN",
            ),
            "chunk_size": _int_input("chunk_size", "Chunk Size", "", value=1000),
            "dimensions": _int_input(
                "dimensions",
                "Dimensions",
                "Output dimensions when the embedding model supports it.",
            ),
            "model_name": _str_input(
                "model_name",
                "Model Name",
                "Embedding model id. Bound to SELECTED_EMBEDDING_MODEL at runtime.",
                value="SELECTED_EMBEDDING_MODEL",
                load_from_db=True,
            ),
        },
    )


def _compute_sha256(index: dict) -> str:
    payload_obj = {key: value for key, value in index.items() if key != "sha256"}
    try:
        import orjson

        payload = orjson.dumps(payload_obj, option=orjson.OPT_SORT_KEYS)
    except ImportError:
        payload = json.dumps(payload_obj, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    openrag = {
        "OpenAICompatibleEmbeddingComponent": embedding_component(),
        "OpenAICompatibleLLMComponent": llm_component(),
    }

    entries = [
        entry for entry in index["entries"] if entry[0] not in {"openrag", BUNDLE_NAME}
    ]
    entries.append([BUNDLE_NAME, openrag])
    entries.sort(key=lambda item: item[0].lower())
    index["entries"] = entries
    index["metadata"] = {
        "num_modules": len(entries),
        "num_components": sum(len(bundle) for _, bundle in entries),
    }
    index["sha256"] = _compute_sha256(index)
    INDEX_PATH.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Updated {INDEX_PATH} "
        f"({index['metadata']['num_modules']} modules, "
        f"{index['metadata']['num_components']} components)"
    )


if __name__ == "__main__":
    main()
