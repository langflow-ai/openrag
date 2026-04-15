"""Shared model constants used across provider/model validation flows."""

ANTHROPIC_VALIDATION_MODELS = [
    "claude-opus-4-5-20251101",
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
]

OPENAI_VALIDATION_MODELS = [
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4-turbo",
    "gpt-4-turbo-preview",
    "gpt-4",
    "gpt-3.5-turbo",
    "o1",
    "o3-mini",
    "o3",
    "o3-pro",
    "o4-mini",
    "o4-mini-high",
]

OPENAI_DEFAULT_LANGUAGE_MODEL = "gpt-4o"

ANTHROPIC_DEFAULT_LANGUAGE_MODEL = "claude-sonnet-4-5-20250929"

OLLAMA_DEFAULT_LANGUAGE_MODEL_PATTERN = "gpt-oss"
