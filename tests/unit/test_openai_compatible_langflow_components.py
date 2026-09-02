"""OpenAI-compatible Langflow components bind proxy globals at runtime."""

import hashlib
import json
from pathlib import Path

# The Langflow bundle is the single home for these components: the former
# ``flows/components`` copies were removed once the bundle became canonical.
BUNDLE = Path("custom_components/bomarag")
# Langflow 1.11 rewrites the bare class name to ``ext:elastic:...@official``
# via its extension migration table, so the BomaRAG copy must be referenced by
# its own canonical extension id everywhere (index key and flow node types).
OPENSEARCH_EXT_ID = "ext:bomarag:OpenSearchVectorStoreComponentMultimodalMultiEmbedding@extra"
OPENSEARCH_MODULE = "_lfx_ext.extra.bomarag.opensearch_multimodal"
# Langflow uses the bundle directory name as the sidebar category label.
BUNDLE_NAME = "BomaRAG"


def test_llm_component_binds_proxy_globals():
    code = (BUNDLE / "openai_compatible_llm.py").read_text(encoding="utf-8")
    assert 'BOMARAG_LLM_BASE_URL_VAR = "BOMARAG_LLM_BASE_URL"' in code
    assert 'BOMARAG_LLM_TOKEN_VAR = "BOMARAG_LLM_TOKEN"' in code
    assert 'SELECTED_LANGUAGE_MODEL_VAR = "SELECTED_LANGUAGE_MODEL"' in code
    assert 'name="api_key"' in code
    assert 'name="api_base"' in code
    assert "load_from_db=True" in code
    assert "ChatOpenAI" in code
    assert "class OpenAICompatibleLLMComponent" in code


def test_embedding_component_uses_the_same_proxy_globals():
    """Embeddings hit /v1/embeddings with the same hop token and /v1 base URL."""
    llm = (BUNDLE / "openai_compatible_llm.py").read_text(encoding="utf-8")
    embedding = (BUNDLE / "openai_compatible_embedding.py").read_text(encoding="utf-8")

    assert 'BOMARAG_LLM_BASE_URL_VAR = "BOMARAG_LLM_BASE_URL"' in embedding
    assert 'BOMARAG_LLM_TOKEN_VAR = "BOMARAG_LLM_TOKEN"' in embedding
    assert 'SELECTED_EMBEDDING_MODEL_VAR = "SELECTED_EMBEDDING_MODEL"' in embedding
    assert 'name="api_key"' in embedding
    assert 'name="api_base"' in embedding
    assert "load_from_db=True" in embedding
    assert "OpenAIEmbeddings" in embedding
    assert "check_embedding_ctx_length" in embedding
    assert "class OpenAICompatibleEmbeddingComponent" in embedding

    assert 'BOMARAG_LLM_BASE_URL_VAR = "BOMARAG_LLM_BASE_URL"' in llm
    assert 'BOMARAG_LLM_TOKEN_VAR = "BOMARAG_LLM_TOKEN"' in llm


def test_langflow_runtime_globals_cover_chat_and_embeddings():
    from api.settings.langflow_sync import (
        LANGFLOW_CREDENTIAL_GLOBAL_VARIABLES,
        LANGFLOW_GENERIC_GLOBAL_VARIABLES,
        LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS,
    )

    assert "BOMARAG_LLM_TOKEN" in LANGFLOW_CREDENTIAL_GLOBAL_VARIABLES
    assert "BOMARAG_LLM_TOKEN" in LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS
    assert {
        "BOMARAG_LLM_BASE_URL",
        "SELECTED_LANGUAGE_MODEL",
        "SELECTED_EMBEDDING_MODEL",
    } <= LANGFLOW_GENERIC_GLOBAL_VARIABLES

    source = Path("src/services/flows_service.py").read_text(encoding="utf-8")
    assert '"api_key": "BOMARAG_LLM_TOKEN"' in source
    assert '"openai_api_key": "BOMARAG_LLM_TOKEN"' in source
    assert '"api_base": "BOMARAG_LLM_BASE_URL"' in source
    assert '"openai_api_base": "BOMARAG_LLM_BASE_URL"' in source


def test_langflow_image_ships_the_bomarag_bundle_as_a_components_path():
    """The BomaRAG components are delivered by scan, not by the component index.

    ``flows/component_index.json`` is Langflow's stock index and carries no
    BomaRAG bundle; the image instead copies ``custom_components/`` in and
    points ``LANGFLOW_COMPONENTS_PATH`` at it, so Langflow discovers the bundle
    when it scans. If that copy or that env var goes away, every flow node
    typed ``ext:bomarag:...`` stops resolving.
    """
    dockerfile = Path("Dockerfile.langflow").read_text(encoding="utf-8")
    assert "COPY custom_components/ /app/custom_components/" in dockerfile
    assert "ENV LANGFLOW_COMPONENTS_PATH=/app/custom_components" in dockerfile

    for name in (
        "openai_compatible_llm.py",
        "openai_compatible_embedding.py",
        "opensearch_multimodal.py",
    ):
        assert (BUNDLE / name).is_file(), name

    index = json.loads(Path("flows/component_index.json").read_text(encoding="utf-8"))
    assert BUNDLE_NAME not in dict(index["entries"])


def test_docker_compose_seeds_bomarag_llm_token_placeholder():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "LANGFLOW_COMPONENTS_INDEX_PATH=/app/flows/component_index.json" in compose
    assert "BOMARAG_LLM_TOKEN=None" in compose
    assert (
        "BOMARAG_LLM_TOKEN"
        in compose.split("LANGFLOW_VARIABLES_TO_GET_FROM_ENVIRONMENT=", 1)[1].split("\n", 1)[0]
    )
    helm = Path("kubernetes/helm/bomarag/templates/langflow/langflow-dotenv.yaml").read_text(
        encoding="utf-8"
    )
    assert 'BOMARAG_LLM_TOKEN="None"' in helm


def test_component_index_sha256_matches_langflow_integrity_check():
    """Langflow recomputes this digest and silently drops a mismatching index.

    It hashes ``orjson.dumps(index_without_sha, option=OPT_SORT_KEYS)``, which
    emits UTF-8 rather than the ASCII escapes ``json.dumps`` produces by
    default. A digest built the other way makes Langflow log
    "SHA256 mismatch" and fall back to a scan with no BomaRAG bundle, which
    blocks every flow that uses one of our components.
    """
    raw = json.loads(Path("flows/component_index.json").read_text(encoding="utf-8"))
    stored = raw.pop("sha256")
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
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


def test_bomarag_bundle_directory_is_lowercase_snake_case():
    """Langflow rejects inline bundle dirs that are not lowercase snake_case."""
    assert BUNDLE.is_dir()
    assert BUNDLE.name.islower()
    assert not Path("custom_components/BomaRAG").is_dir() or BUNDLE.samefile(
        Path("custom_components/BomaRAG")
    )


def test_embedding_component_pins_deployment_to_the_configured_model():
    """`OpenAIEmbeddings.deployment` must not keep LangChain's class default.

    That default is the literal "text-embedding-ada-002" for every instance,
    whatever model is configured. The OpenSearch component keys its embedding
    lookup on `deployment` as well as `model`, so the default registers a
    768-dim watsonx embedder under ada-002 and OpenSearch then rejects the
    search with "Query vector has invalid dimension: 768. Dimension should be:
    1536".
    """
    code = (BUNDLE / "openai_compatible_embedding.py").read_text(encoding="utf-8")
    assert '"deployment": self.model_name' in code


def test_flows_embed_the_current_proxy_component_sources():
    """Flow JSONs carry their own copy of each component; keep them in step.

    A fix applied only to `custom_components/` never reaches a running flow,
    because Langflow executes the code embedded in the flow node.
    """
    for name, node_type in (
        ("openai_compatible_embedding.py", "OpenAICompatibleEmbedding"),
        ("openai_compatible_llm.py", "OpenAICompatibleLLM"),
    ):
        source = (BUNDLE / name).read_text(encoding="utf-8")
        expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]

        for path in sorted(Path("flows").glob("*.json")):
            if path.name == "component_index.json":
                continue
            flow = json.loads(path.read_text(encoding="utf-8"))
            for node in flow.get("data", {}).get("nodes", []):
                if node.get("data", {}).get("type") != node_type:
                    continue
                component = node["data"]["node"]
                assert component["template"]["code"]["value"] == source, (
                    f"{path.name}: embedded {name} is out of sync with the bundle"
                )
                assert component.get("metadata", {}).get("code_hash") == expected_hash, (
                    f"{path.name}: {node_type} metadata.code_hash is stale"
                )
