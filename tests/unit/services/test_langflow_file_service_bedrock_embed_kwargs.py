"""Langflow-ingest preflight coverage for AWS Bedrock embedding calls.

``LangflowFileService._detect_embedding_dimensions`` is the third
``clients.patched_embedding_client.embeddings.create(...)`` call site in the
codebase, alongside ``services.search_service`` (query embeddings, now routed
through the gateway) and ``models.processors`` (non-Langflow ingest
embeddings). It fires one probe embedding so ``_ensure_langflow_ingest_index``
can pre-create the OpenSearch knn_vector mapping with the right dimension
count -- Langflow itself cannot, because it ingests with a DLS-scoped JWT.

Like the ingest path in ``models.processors``, it must pass Cohere's
``input_type`` (no default - every call requires one) and Bedrock's AWS
credentials as call-time kwargs rather than relying on the process-wide
AWS_* env vars the S3 connector also reads. Before this fix neither was
forwarded, so the probe either raised on litellm's Cohere transformation
layer (missing input_type) or authenticated with whatever credentials
happened to be in the process environment instead of the configured ones.
That exception is caught by ``_ensure_langflow_ingest_index``'s broad
``except``, which only logs a warning -- so the gap did not surface as an
error, it silently skipped index pre-creation for Bedrock deployments.
"""

from types import SimpleNamespace

import pytest

from services.langflow_file_service import LangflowFileService


def _bedrock_config(*, access_key_id="", secret_access_key="", region="us-east-1"):
    return SimpleNamespace(
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
    )


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
async def test_dimension_probe_passes_cohere_input_type_and_bedrock_credentials(monkeypatch):
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "bedrock/cohere.embed-multilingual-v3")
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(
            providers=SimpleNamespace(
                bedrock=_bedrock_config(
                    access_key_id="AKIAEXAMPLE", secret_access_key="supersecret"
                )
            )
        ),
    )

    service = LangflowFileService()
    dimensions = await service._detect_embedding_dimensions(
        "cohere.embed-multilingual-v3", "bedrock"
    )

    assert dimensions == 1024
    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["model"] == "bedrock/cohere.embed-multilingual-v3"
    assert call["input"] == ["dimension probe"]
    # Probe sizes the index for ingested documents, so it mirrors the ingest
    # path's input_type rather than search_service's search_query.
    assert call["input_type"] == "search_document"
    assert call["aws_access_key_id"] == "AKIAEXAMPLE"
    assert call["aws_secret_access_key"] == "supersecret"
    assert call["aws_region_name"] == "us-east-1"


@pytest.mark.asyncio
async def test_dimension_probe_omits_credentials_in_iam_role_mode(monkeypatch):
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "bedrock/cohere.embed-multilingual-v3")
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: SimpleNamespace(providers=SimpleNamespace(bedrock=_bedrock_config())),
    )

    service = LangflowFileService()
    await service._detect_embedding_dimensions("cohere.embed-multilingual-v3", "bedrock")

    call = captured_calls[0]
    assert "aws_access_key_id" not in call
    assert "aws_secret_access_key" not in call
    # Region is still required in IAM-role mode.
    assert call["aws_region_name"] == "us-east-1"


@pytest.mark.asyncio
async def test_dimension_probe_sends_no_extra_kwargs_for_openai_model(monkeypatch):
    """Sanity check: a non-Bedrock, non-Cohere model gets model/input only, so
    the fix cannot regress the OpenAI/watsonx/ollama probe path."""
    captured_calls = []
    _patch_embedding_client(monkeypatch, captured_calls)
    _patch_models_service(monkeypatch, "text-embedding-3-small")

    service = LangflowFileService()
    await service._detect_embedding_dimensions("text-embedding-3-small", "openai")

    assert set(captured_calls[0]) == {"model", "input"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
