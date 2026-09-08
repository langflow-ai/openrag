"""Preferred default model IDs used when a live provider list is available.

Live provider APIs are the source of truth for which models appear in pickers.
These constants are soft preferences: used when present in the live list, and
as thin offline fallbacks when a live fetch is unavailable.
"""

OPENAI_DEFAULT_LANGUAGE_MODEL = "gpt-5.4-mini"

ANTHROPIC_DEFAULT_LANGUAGE_MODEL = "claude-sonnet-4-6"

OLLAMA_DEFAULT_LANGUAGE_MODEL_PATTERN = "gpt-oss"
