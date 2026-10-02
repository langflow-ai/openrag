"""Langflow-ingest preflight coverage for OCI Generative AI embedding calls.

``LangflowFileService._detect_embedding_dimensions`` is the third
``clients.patched_embedding_client.embeddings.create(...)`` call site in the
codebase, alongside ``services.search_service`` (query embeddings) and
``models.processors`` (non-Langflow ingest embeddings). It fires one probe
embedding so ``_ensure_langflow_ingest_index`` can pre-create the OpenSearch
knn_vector mapping with the right dimension count -- Langflow itself cannot,
because it ingests with a DLS-scoped JWT.

Like the other two sites, it must pass the ``oci_*`` credential kwargs
explicitly: litellm's OCI integration reads them exclusively from call-time
kwargs (see ``OCIEmbeddingConfig.validate_environment`` in
litellm/llms/oci/embed/transformation.py), never from the environment, and
raises without them. That exception is caught by
``_ensure_langflow_ingest_index``'s broad ``except``, which only logs a
warning -- so a missing credential kwarg does not surface as an error, it
silently skips index pre-creation for every OCI deployment.
"""

from types import SimpleNamespace

import pytest

from services.langflow_file_service import LangflowFileService


def _oci_config(**overrides):
    base = dict(
        user="ocid1.user.oc1..xxx",
        fingerprint="xx:xx:xx:xx",
        tenancy="ocid1.tenancy.oc1..xxx",
        compartment_id="ocid1.compartment.oc1..xxx",
        key="",
        key_file="/tmp/oci_key.pem",
        region="us-ashburn-1",
        configured=True,
        auth_method="api_key",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_embedding_client(monkeypatch, captured_calls):
    class FakeEmbeddings:
        async def create(self, model, input, **kwargs):
            captured_calls.append({"model": model, "input": input, **kwargs})
            return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1] * 1024)])

    class FakeEmbeddingClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(
        "services.langflow_file_service.clients",
        SimpleNamespace(patched_embedding_client=FakeEmbeddingClient()),
    )


def _patch_models_service(monkeypatch, litellm_name):
    class FakeModelsService:
        async def get_litellm_model_name(self, model_name, provider=None):
            return litellm_name

    monkeypatch.setattr("services.models_service.ModelsService", FakeModelsService)


@pytest.mark.asyncio
async def test_dimension_probe_passes_cohere_input_type_and_oci_credentials(monkeypatch):
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "oci/cohere.embed-multilingual-v3.0")
    monkeypatch.setattr(
        "services.langflow_file_service.get_openrag_config",
        lambda: SimpleNamespace(providers=SimpleNamespace(oci=_oci_config())),
    )

    service = LangflowFileService()
    dimensions = await service._detect_embedding_dimensions("cohere.embed-multilingual-v3.0", "oci")

    assert dimensions == 1024
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["model"] == "oci/cohere.embed-multilingual-v3.0"
    assert call["input"] == ["dimension probe"]
    # Probe sizes the index for ingested documents, so it mirrors the ingest
    # path's input_type rather than search_service's search_query.
    assert call["input_type"] == "search_document"
    assert call["oci_user"] == "ocid1.user.oc1..xxx"
    assert call["oci_fingerprint"] == "xx:xx:xx:xx"
    assert call["oci_tenancy"] == "ocid1.tenancy.oc1..xxx"
    assert call["oci_compartment_id"] == "ocid1.compartment.oc1..xxx"
    assert call["oci_key_file"] == "/tmp/oci_key.pem"
    assert call["oci_region"] == "us-ashburn-1"
    # Empty string ("key" not set) must not be forwarded as a kwarg.
    assert "oci_key" not in call


@pytest.mark.asyncio
async def test_dimension_probe_forwards_prebuilt_signer_for_instance_principal(monkeypatch):
    """instance_principal/workload_identity sign via a prebuilt OCI SDK Signer;
    the manual key fields must not be sent alongside it."""
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "oci/cohere.embed-multilingual-v3.0")
    monkeypatch.setattr(
        "services.langflow_file_service.get_openrag_config",
        lambda: SimpleNamespace(
            providers=SimpleNamespace(
                oci=_oci_config(auth_method="instance_principal", user="", key_file="")
            )
        ),
    )
    sentinel_signer = object()
    monkeypatch.setattr(
        "services.langflow_file_service.get_cached_oci_signer",
        lambda auth_method: sentinel_signer if auth_method == "instance_principal" else None,
    )

    service = LangflowFileService()
    dimensions = await service._detect_embedding_dimensions("cohere.embed-multilingual-v3.0", "oci")

    assert dimensions == 1024
    call = captured_calls[0]
    assert call["oci_signer"] is sentinel_signer
    assert call["oci_compartment_id"] == "ocid1.compartment.oc1..xxx"
    assert call["oci_region"] == "us-ashburn-1"
    assert not any(
        k in call for k in ("oci_user", "oci_fingerprint", "oci_tenancy", "oci_key", "oci_key_file")
    )


@pytest.mark.asyncio
async def test_dimension_probe_sends_no_extra_kwargs_for_openai_model(monkeypatch):
    """Sanity check: a non-OCI, non-Cohere model gets model/input only, so the
    fix cannot regress the OpenAI/watsonx/ollama probe path."""
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "text-embedding-3-small")

    service = LangflowFileService()
    await service._detect_embedding_dimensions("text-embedding-3-small", "openai")

    assert set(captured_calls[0]) == {"model", "input"}
