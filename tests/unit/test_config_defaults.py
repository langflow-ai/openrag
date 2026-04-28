import config.config_manager as config_manager
from config.settings import _resolve_default_docs_ingest_source


def test_default_docs_ingest_source_ignores_url_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_DOCS_INGEST_SOURCE", "url")

    assert _resolve_default_docs_ingest_source() == "files"


def test_default_docs_ingest_source_allows_files_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_DOCS_INGEST_SOURCE", "FILES")

    assert _resolve_default_docs_ingest_source() == "files"


def test_agent_config_preserves_custom_prompt_with_url_ingestion_text():
    custom_prompt = (
        "Keep this custom prompt even though it mentions URL Ingestion Tool "
        "and URL Ingestion Rules in a migration note."
    )

    config = config_manager.AgentConfig(system_prompt=custom_prompt)

    assert config.system_prompt == custom_prompt


def test_agent_config_migrates_known_legacy_default_prompt(monkeypatch):
    legacy_prompt = "legacy prompt with URL Ingestion Tool and URL Ingestion Rules"
    legacy_prompt_hash = config_manager._normalized_prompt_hash(legacy_prompt)
    monkeypatch.setattr(
        config_manager,
        "LEGACY_DEFAULT_SYSTEM_PROMPT_HASHES",
        frozenset({legacy_prompt_hash}),
    )

    config = config_manager.AgentConfig(system_prompt=legacy_prompt)

    assert config.system_prompt == config_manager.DEFAULT_SYSTEM_PROMPT
