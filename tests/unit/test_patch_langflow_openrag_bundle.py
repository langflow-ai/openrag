"""Langflow SIDEBAR_BUNDLES patch registers the OpenRAG custom-component group."""

import importlib.util
from pathlib import Path

SCRIPT = Path("scripts/patch_langflow_openrag_bundle.py")


def _load():
    spec = importlib.util.spec_from_file_location("patch_langflow_openrag_bundle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patch_inserts_pretty_typescript_entries_for_both_folder_casings():
    patch = _load()
    source = """export const SIDEBAR_BUNDLES = [
 { display_name: "OpenAI", name: "openai", icon: "OpenAI" },
 { display_name: "OpenRouter", name: "openrouter", icon: "OpenRouter" },
];
"""
    updated = patch.patch_text(source)
    assert updated is not None
    assert '{ display_name: "OpenRAG", name: "OpenRAG", icon: "OpenRAG" }' in updated
    assert '{ display_name: "OpenRAG", name: "openrag", icon: "OpenRAG" }' in updated
    assert updated.index("OpenAI") < updated.index('name: "OpenRAG"') < updated.index("OpenRouter")
    assert patch.patch_text(updated) == updated


def test_patch_inserts_minified_javascript_entries():
    patch = _load()
    source = (
        'var B=[{display_name:"OpenAI",name:"openai",icon:"OpenAI"},'
        '{display_name:"OpenRouter",name:"openrouter",icon:"OpenRouter"}];'
    )
    updated = patch.patch_text(source)
    assert updated is not None
    assert '{display_name:"OpenRAG",name:"OpenRAG",icon:"OpenRAG"}' in updated
    assert '{display_name:"OpenRAG",name:"openrag",icon:"OpenRAG"}' in updated
    assert patch.patch_text(updated) == updated


def test_patch_inserts_quoted_json_keys_used_by_some_bundlers():
    patch = _load()
    source = (
        '[{"display_name":"OpenAI","name":"openai","icon":"OpenAI"},'
        '{"display_name":"OpenRouter","name":"openrouter","icon":"OpenRouter"}]'
    )
    updated = patch.patch_text(source)
    assert updated is not None
    assert '{"display_name":"OpenRAG","name":"OpenRAG","icon":"OpenRAG"}' in updated
    assert '{"display_name":"OpenRAG","name":"openrag","icon":"OpenRAG"}' in updated
    assert patch.patch_text(updated) == updated


def test_patch_adds_lowercase_name_when_title_case_already_exists():
    patch = _load()
    source = """export const SIDEBAR_BUNDLES = [
 { display_name: "OpenAI", name: "openai", icon: "OpenAI" },
 { display_name: "OpenRAG", name: "OpenRAG", icon: "OpenRAG" },
 { display_name: "OpenRouter", name: "openrouter", icon: "OpenRouter" },
];
"""
    updated = patch.patch_text(source)
    assert updated is not None
    assert '{ display_name: "OpenRAG", name: "openrag", icon: "OpenRAG" }' in updated
    assert updated.count('{ display_name: "OpenRAG", name: "OpenRAG", icon: "OpenRAG" }') == 1
    assert patch.patch_text(updated) == updated


def test_patch_files_and_dockerfiles_wire_the_script(tmp_path):
    patch = _load()
    target = tmp_path / "styleUtils.ts"
    target.write_text(
        '{ display_name: "Docling", name: "docling", icon: "Docling" },\n',
        encoding="utf-8",
    )
    assert patch.patch_paths([target]) == 1
    text = target.read_text(encoding="utf-8")
    assert '{ display_name: "OpenRAG", name: "OpenRAG", icon: "OpenRAG" }' in text
    assert '{ display_name: "OpenRAG", name: "openrag", icon: "OpenRAG" }' in text

    prod = Path("Dockerfile.langflow").read_text(encoding="utf-8")
    dev = Path("Dockerfile.langflow.dev").read_text(encoding="utf-8")
    assert "patch_langflow_openrag_bundle.py" in prod
    assert "python3 /tmp/patch_langflow_openrag_bundle.py" in prod
    assert "patch_langflow_openrag_bundle.py" in dev
    assert "styleUtils.ts" in dev
