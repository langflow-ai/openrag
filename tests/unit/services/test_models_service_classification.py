"""Unit tests for OpenAI model classification and preferred-model resolution."""

from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
from config.model_constants import OPENAI_DEFAULT_LANGUAGE_MODEL
from services.models_service import (
    is_openai_embedding_model,
    is_openai_language_model,
    is_openai_non_chat_model,
    resolve_preferred_model,
)


class TestOpenAIEmbeddingClassification:
    def test_text_embedding_models(self):
        assert is_openai_embedding_model("text-embedding-3-small")
        assert is_openai_embedding_model("text-embedding-3-large")
        assert is_openai_embedding_model("text-embedding-ada-002")

    def test_text_similarity_models(self):
        assert is_openai_embedding_model("text-similarity-davinci-001")

    def test_chat_models_are_not_embeddings(self):
        assert not is_openai_embedding_model("gpt-5.4-mini")
        assert not is_openai_embedding_model("o4-mini")


class TestOpenAINonChatClassification:
    def test_whisper_dalle_tts_moderation(self):
        assert is_openai_non_chat_model("whisper-1")
        assert is_openai_non_chat_model("dall-e-3")
        assert is_openai_non_chat_model("tts-1")
        assert is_openai_non_chat_model("tts-1-hd")
        assert is_openai_non_chat_model("omni-moderation-latest")
        assert is_openai_non_chat_model("text-moderation-latest")
        assert is_openai_non_chat_model("gpt-4o-moderation")

    def test_image_audio_realtime_variants(self):
        assert is_openai_non_chat_model("gpt-image-1")
        assert is_openai_non_chat_model("gpt-audio-1")
        assert is_openai_non_chat_model("gpt-realtime")
        assert is_openai_non_chat_model("gpt-4o-realtime-preview")
        assert is_openai_non_chat_model("gpt-4o-transcribe")
        assert is_openai_non_chat_model("gpt-4o-mini-tts")

    def test_chat_models_are_not_junk(self):
        assert not is_openai_non_chat_model("gpt-5.4-mini")
        assert not is_openai_non_chat_model("o4-mini")
        assert not is_openai_non_chat_model("chatgpt-4o-latest")


class TestOpenAILanguageClassification:
    def test_gpt_and_chatgpt_families(self):
        assert is_openai_language_model("gpt-5.4-mini")
        assert is_openai_language_model("gpt-4o")
        assert is_openai_language_model("gpt-4.1")
        assert is_openai_language_model("chatgpt-4o-latest")

    def test_reasoning_o_families_including_o4(self):
        assert is_openai_language_model("o1")
        assert is_openai_language_model("o1-mini")
        assert is_openai_language_model("o3")
        assert is_openai_language_model("o3-pro")
        assert is_openai_language_model("o4-mini")
        assert is_openai_language_model("o4-mini-high")

    def test_excludes_embeddings_and_junk(self):
        assert not is_openai_language_model("text-embedding-3-small")
        assert not is_openai_language_model("whisper-1")
        assert not is_openai_language_model("dall-e-3")
        assert not is_openai_language_model("gpt-image-1")
        assert not is_openai_language_model("omni-moderation-latest")
        assert not is_openai_language_model("gpt-4o-realtime-preview")
        assert not is_openai_language_model("gpt-4o-transcribe")
        assert not is_openai_language_model("gpt-4o-mini-tts")

    def test_excludes_empty_id(self):
        assert not is_openai_language_model("")

    def test_fine_tuned_gpt_models(self):
        assert is_openai_language_model("ft:gpt-4o:org:custom")
        assert is_openai_language_model("ft:gpt-4.1-mini:acme:my-tune:abc123")


class TestRelaxedClassificationForCustomGateways:
    """A custom base_url means the inventory isn't OpenAI's own catalog, so
    naming-scheme-based classification is relaxed instead of dropping every
    non-matching model ID (openrag issue #2060 - custom gateway onboarding)."""

    def test_relaxed_embedding_matches_on_embed_substring(self):
        assert is_openai_embedding_model("cohere.embed-english-v3", relaxed=True)
        assert is_openai_embedding_model("stub-embed-model", relaxed=True)
        assert not is_openai_embedding_model("stub-embed-model", relaxed=False)

    def test_relaxed_language_model_accepts_non_openai_names(self):
        assert is_openai_language_model("stub-chat-model", relaxed=True)
        assert is_openai_language_model("claude-3-opus", relaxed=True)
        assert not is_openai_language_model("stub-chat-model", relaxed=False)

    def test_relaxed_still_excludes_embeddings_and_junk(self):
        assert not is_openai_language_model("stub-embed-model", relaxed=True)
        assert not is_openai_language_model("whisper-1", relaxed=True)
        assert not is_openai_language_model("dall-e-3", relaxed=True)

    def test_strict_openai_names_unaffected_by_relaxed(self):
        assert is_openai_language_model("gpt-4o", relaxed=True)
        assert is_openai_embedding_model("text-embedding-3-small", relaxed=True)


class TestResolvePreferredModel:
    def test_uses_preferred_when_present(self):
        live = [
            {"value": "gpt-4o", "default": False},
            {"value": OPENAI_DEFAULT_LANGUAGE_MODEL, "default": False},
        ]
        assert (
            resolve_preferred_model(OPENAI_DEFAULT_LANGUAGE_MODEL, live)
            == OPENAI_DEFAULT_LANGUAGE_MODEL
        )

    def test_uses_live_default_when_preferred_missing(self):
        live = [
            {"value": "gpt-4o", "default": False},
            {"value": "o4-mini", "default": True},
        ]
        assert resolve_preferred_model("gpt-missing", live) == "o4-mini"

    def test_uses_first_when_preferred_and_default_missing(self):
        live = [
            {"value": "o4-mini", "default": False},
            {"value": "gpt-4o", "default": False},
        ]
        assert resolve_preferred_model("gpt-missing", live) == "o4-mini"

    def test_empty_live_list_returns_preferred(self):
        assert (
            resolve_preferred_model(OPENAI_DEFAULT_LANGUAGE_MODEL, [])
            == OPENAI_DEFAULT_LANGUAGE_MODEL
        )
        assert resolve_preferred_model("", []) == ""

    def test_embedding_preferred(self):
        live = [
            {"value": "text-embedding-3-large", "default": False},
            {"value": OPENAI_DEFAULT_EMBEDDING_MODEL, "default": False},
        ]
        assert (
            resolve_preferred_model(OPENAI_DEFAULT_EMBEDDING_MODEL, live)
            == OPENAI_DEFAULT_EMBEDDING_MODEL
        )
