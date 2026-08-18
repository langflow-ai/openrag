"""OpenAI-compatible Langflow components bind proxy globals at runtime."""

import hashlib
import json
from pathlib import Path

COMPONENTS = Path("flows/components")
BUNDLE = Path("custom_components/openrag")
# Langflow 1.11 rewrites the bare class name to ``ext:elastic:...@official``
# via its extension migration table, so the OpenRAG copy must be referenced by
# its own canonical extension id everywhere (index key and flow node types).
OPENSEARCH_EXT_ID = "ext:openrag:OpenSearchVectorStoreComponentMultimodalMultiEmbedding@extra"
OPENSEARCH_MODULE = "_lfx_ext.extra.openrag.opensearch_multimodal"


def test_llm_component_binds_proxy_globals():
    code = (COMPONENTS / "openai_compatible_llm.py").read_text(encoding="utf-8")
    assert 'OPENRAG_LLM_BASE_URL_VAR = "OPENRAG_LLM_BASE_URL"' in code
    assert 'OPENRAG_LLM_TOKEN_VAR = "OPENRAG_LLM_TOKEN"' in code
    assert 'SELECTED_LANGUAGE_MODEL_VAR = "SELECTED_LANGUAGE_MODEL"' in code
    assert 'name="api_key"' in code
    assert 'name="api_base"' in code
    assert "load_from_db=True" in code
    assert "ChatOpenAI" in code
    assert "class OpenAICompatibleLLMComponent" in code


def test_embedding_component_uses_the_same_proxy_globals():
    """Embeddings hit /v1/embeddings with the same hop token and /v1 base URL."""
    llm = (COMPONENTS / "openai_compatible_llm.py").read_text(encoding="utf-8")
    embedding = (COMPONENTS / "openai_compatible_embedding.py").read_text(encoding="utf-8")

    assert 'OPENRAG_LLM_BASE_URL_VAR = "OPENRAG_LLM_BASE_URL"' in embedding
    assert 'OPENRAG_LLM_TOKEN_VAR = "OPENRAG_LLM_TOKEN"' in embedding
    assert 'SELECTED_EMBEDDING_MODEL_VAR = "SELECTED_EMBEDDING_MODEL"' in embedding
    assert 'name="api_key"' in embedding
    assert 'name="api_base"' in embedding
    assert "load_from_db=True" in embedding
    assert "OpenAIEmbeddings" in embedding
    assert "check_embedding_ctx_length" in embedding
    assert "class OpenAICompatibleEmbeddingComponent" in embedding

    assert 'OPENRAG_LLM_BASE_URL_VAR = "OPENRAG_LLM_BASE_URL"' in llm
    assert 'OPENRAG_LLM_TOKEN_VAR = "OPENRAG_LLM_TOKEN"' in llm


def test_langflow_runtime_globals_cover_chat_and_embeddings():
    from api.settings.langflow_sync import (
        LANGFLOW_CREDENTIAL_GLOBAL_VARIABLES,
        LANGFLOW_GENERIC_GLOBAL_VARIABLES,
        LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS,
    )

    assert "OPENRAG_LLM_TOKEN" in LANGFLOW_CREDENTIAL_GLOBAL_VARIABLES
    assert "OPENRAG_LLM_TOKEN" in LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS
    assert {
        "OPENRAG_LLM_BASE_URL",
        "SELECTED_LANGUAGE_MODEL",
        "SELECTED_EMBEDDING_MODEL",
    } <= LANGFLOW_GENERIC_GLOBAL_VARIABLES

    source = Path("src/services/flows_service.py").read_text(encoding="utf-8")
    assert '"api_key": "OPENRAG_LLM_TOKEN"' in source
    assert '"openai_api_key": "OPENRAG_LLM_TOKEN"' in source
    assert '"api_base": "OPENRAG_LLM_BASE_URL"' in source
    assert '"openai_api_base": "OPENRAG_LLM_BASE_URL"' in source


def test_custom_components_stay_in_sync_with_flows_components():
    for name in (
        "openai_compatible_llm.py",
        "openai_compatible_embedding.py",
        "opensearch_multimodal.py",
    ):
        canonical = (COMPONENTS / name).read_text(encoding="utf-8")
        bundled = (BUNDLE / name).read_text(encoding="utf-8")
        assert bundled == canonical


def test_component_index_registers_openrag_proxy_components():
    index = json.loads(Path("flows/component_index.json").read_text(encoding="utf-8"))
    bundles = dict(index["entries"])
    assert "OpenRAG" in bundles
    assert "openrag" not in bundles
    openrag = bundles["OpenRAG"]
    llm = openrag["OpenAICompatibleLLMComponent"]
    embedding = openrag["OpenAICompatibleEmbeddingComponent"]
    assert "OpenSearchVectorStoreComponentMultimodalMultiEmbedding" not in openrag
    opensearch = openrag[OPENSEARCH_EXT_ID]
    source = (COMPONENTS / "opensearch_multimodal.py").read_text(encoding="utf-8")

    assert llm["template"]["api_key"]["value"] == "OPENRAG_LLM_TOKEN"
    assert llm["template"]["api_key"]["load_from_db"] is True
    assert llm["template"]["api_base"]["value"] == "OPENRAG_LLM_BASE_URL"
    assert llm["template"]["api_base"]["load_from_db"] is True
    assert llm["template"]["model_name"]["value"] == "SELECTED_LANGUAGE_MODEL"

    assert embedding["template"]["api_key"]["value"] == "OPENRAG_LLM_TOKEN"
    assert embedding["template"]["api_key"]["load_from_db"] is True
    assert embedding["template"]["api_base"]["value"] == "OPENRAG_LLM_BASE_URL"
    assert llm["display_name"] == "OpenRAG LLM"
    assert embedding["display_name"] == "OpenRAG Embeddings"
    assert llm["icon"] == "OpenRAG"
    assert embedding["icon"] == "OpenRAG"
    assert llm["metadata"]["module"].startswith("custom_components.OpenRAG.")
    assert opensearch["display_name"] == "OpenSearch (Multi-Model Multi-Embedding)"
    assert opensearch["icon"] == "OpenSearch"
    assert opensearch["edited"] is False
    assert opensearch["template"]["code"]["value"] == source
    assert opensearch["metadata"]["module"] == OPENSEARCH_MODULE
    assert opensearch["metadata"]["code_hash"] == hashlib.sha256(source.encode("utf-8")).hexdigest()[
        :12
    ]


def test_docker_compose_seeds_openrag_llm_token_placeholder():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "LANGFLOW_COMPONENTS_INDEX_PATH=/app/flows/component_index.json" in compose
    assert "OPENRAG_LLM_TOKEN=None" in compose
    assert "OPENRAG_LLM_TOKEN" in compose.split(
        "LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT=", 1
    )[1].split("\n", 1)[0]
    helm = Path("kubernetes/helm/openrag/templates/langflow/langflow-dotenv.yaml").read_text(
        encoding="utf-8"
    )
    assert 'OPENRAG_LLM_TOKEN="None"' in helm


def test_component_index_sha256_matches_langflow_integrity_check():
    """Langflow recomputes this digest and silently drops a mismatching index.

    It hashes ``orjson.dumps(index_without_sha, option=OPT_SORT_KEYS)``, which
    emits UTF-8 rather than the ASCII escapes ``json.dumps`` produces by
    default. A digest built the other way makes Langflow log
    "SHA256 mismatch" and fall back to a scan with no OpenRAG bundle, which
    blocks every flow that uses one of our components.
    """
    raw = json.loads(Path("flows/component_index.json").read_text(encoding="utf-8"))
    stored = raw.pop("sha256")
    payload = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert stored == hashlib.sha256(payload).hexdigest()


def test_flows_reference_opensearch_by_canonical_extension_id():
    """A bare class-name reference gets hijacked by Langflow's migration table."""
    for path in sorted(Path("flows").glob("*.json")):
        if path.name == "component_index.json":
            continue
        flow = json.loads(path.read_text(encoding="utf-8"))
        for node in flow.get("data", {}).get("nodes", []):
            node_type = node.get("data", {}).get("type")
            if node_type and "OpenSearchVectorStoreComponentMultimodalMultiEmbedding" in node_type:
                assert node_type == OPENSEARCH_EXT_ID, path.name
                metadata = node["data"]["node"].get("metadata") or {}
                assert metadata.get("module") == OPENSEARCH_MODULE, path.name


def test_openrag_bundle_directory_is_lowercase_snake_case():
    """Langflow rejects inline bundle dirs that are not lowercase snake_case."""
    assert BUNDLE.is_dir()
    assert BUNDLE.name.islower()
    assert not Path("custom_components/OpenRAG").is_dir() or BUNDLE.samefile(
        Path("custom_components/OpenRAG")
    )
