"""Unit tests for ``utils.embedding_kwargs``.

Covers the two decision points that make Cohere-family embedding calls
(currently: OCI Generative AI) work correctly through the ``agentd``
litellm-passthrough path:
  1. Detecting a Cohere-family model by name (not by resolved provider).
  2. Building the oci_* credential kwargs litellm's OCI integration reads
     exclusively from call-time kwargs (never from the environment).
"""

from types import SimpleNamespace

from utils.embedding_kwargs import (
    COHERE_DOCUMENT_INPUT_TYPE,
    COHERE_QUERY_INPUT_TYPE,
    cohere_input_type_kwargs,
    is_cohere_embedding_model,
    is_oci_litellm_model,
    oci_credential_kwargs,
)


class TestIsCohereEmbeddingModel:
    def test_bare_cohere_model_name(self):
        assert is_cohere_embedding_model("cohere.embed-multilingual-v3.0") is True

    def test_oci_prefixed_cohere_model_name(self):
        assert is_cohere_embedding_model("oci/cohere.embed-multilingual-v3.0") is True

    def test_case_insensitive(self):
        assert is_cohere_embedding_model("Cohere.Embed-V4.0") is True

    def test_non_cohere_model(self):
        assert is_cohere_embedding_model("text-embedding-3-small") is False

    def test_empty_string(self):
        assert is_cohere_embedding_model("") is False

    def test_none(self):
        assert is_cohere_embedding_model(None) is False


class TestCohereInputTypeKwargs:
    def test_cohere_model_gets_input_type(self):
        kwargs = cohere_input_type_kwargs("oci/cohere.embed-multilingual-v3.0", COHERE_QUERY_INPUT_TYPE)
        assert kwargs == {"input_type": "search_query"}

    def test_document_input_type_value(self):
        kwargs = cohere_input_type_kwargs("cohere.embed-v4.0", COHERE_DOCUMENT_INPUT_TYPE)
        assert kwargs == {"input_type": "search_document"}

    def test_non_cohere_model_gets_no_kwargs(self):
        assert cohere_input_type_kwargs("text-embedding-3-small", COHERE_QUERY_INPUT_TYPE) == {}

    def test_empty_model_name_gets_no_kwargs(self):
        assert cohere_input_type_kwargs("", COHERE_QUERY_INPUT_TYPE) == {}


class TestIsOciLitellmModel:
    def test_oci_prefixed_model(self):
        assert is_oci_litellm_model("oci/cohere.embed-multilingual-v3.0") is True

    def test_non_oci_model(self):
        assert is_oci_litellm_model("watsonx/ibm/slate-125m-english-rtrvr") is False

    def test_bare_cohere_model_without_prefix(self):
        # Not yet resolved to a litellm-routable string -- no oci/ prefix present.
        assert is_oci_litellm_model("cohere.embed-multilingual-v3.0") is False

    def test_empty_string(self):
        assert is_oci_litellm_model("") is False

    def test_none(self):
        assert is_oci_litellm_model(None) is False


class TestOciCredentialKwargs:
    def test_full_credentials_with_inline_key(self):
        oci_config = SimpleNamespace(
            user="ocid1.user.oc1..xxx",
            fingerprint="xx:xx:xx:xx",
            tenancy="ocid1.tenancy.oc1..xxx",
            compartment_id="ocid1.compartment.oc1..xxx",
            key="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
            key_file="",
            region="us-ashburn-1",
        )
        kwargs = oci_credential_kwargs(oci_config)
        assert kwargs == {
            "oci_user": "ocid1.user.oc1..xxx",
            "oci_fingerprint": "xx:xx:xx:xx",
            "oci_tenancy": "ocid1.tenancy.oc1..xxx",
            "oci_compartment_id": "ocid1.compartment.oc1..xxx",
            "oci_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
            "oci_region": "us-ashburn-1",
        }
        assert "oci_key_file" not in kwargs

    def test_full_credentials_with_key_file(self):
        oci_config = SimpleNamespace(
            user="ocid1.user.oc1..xxx",
            fingerprint="xx:xx:xx:xx",
            tenancy="ocid1.tenancy.oc1..xxx",
            compartment_id="ocid1.compartment.oc1..xxx",
            key="",
            key_file="/home/user/.oci/key.pem",
            region="us-ashburn-1",
        )
        kwargs = oci_credential_kwargs(oci_config)
        assert kwargs["oci_key_file"] == "/home/user/.oci/key.pem"
        assert "oci_key" not in kwargs

    def test_empty_config_yields_empty_kwargs(self):
        oci_config = SimpleNamespace(
            user="", fingerprint="", tenancy="", compartment_id="", key="", key_file="", region=""
        )
        assert oci_credential_kwargs(oci_config) == {}

    def test_missing_attributes_are_tolerated(self):
        # getattr(..., None) guards -- an object with none of the expected
        # attributes should not raise, just yield an empty dict.
        assert oci_credential_kwargs(object()) == {}

    def test_region_omitted_when_not_set(self):
        oci_config = SimpleNamespace(
            user="u", fingerprint="f", tenancy="t", compartment_id="c", key="k", key_file="", region=""
        )
        kwargs = oci_credential_kwargs(oci_config)
        assert "oci_region" not in kwargs
