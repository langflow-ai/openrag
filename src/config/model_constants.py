"""Shared model constants used across provider/model validation flows."""

ANTHROPIC_VALIDATION_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5-20250929",
]

OPENAI_VALIDATION_MODELS = [
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-pro",
    "gpt-5.3-codex",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o3",
    "o3-pro",
    "o4-mini-high",
]

OPENAI_DEFAULT_LANGUAGE_MODEL = "gpt-5.4-mini"

ANTHROPIC_DEFAULT_LANGUAGE_MODEL = "claude-sonnet-4-6"

OLLAMA_DEFAULT_LANGUAGE_MODEL_PATTERN = "gpt-oss"
