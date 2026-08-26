"""Per-run-mode model provider visibility (`config/model_providers.yaml`).

The config file is the only place that decides which providers Settings,
Onboarding and the model pickers offer, so these tests pin the rules the file
promises: run mode is the switch, a missing mode key hides, an unlisted
provider is never offered, and an override file wins over the shipped one.
"""

from __future__ import annotations

import pytest

from config import model_providers


@pytest.fixture(autouse=True)
def _fresh_config():
    """Each test parses the file itself; never inherit another test's cache."""
    model_providers.reload()
    yield
    model_providers.reload()


def _write(tmp_path, body: str) -> str:
    path = tmp_path / "model_providers.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_shipped_defaults_keep_ollama_out_of_saas_only(monkeypatch):
    for mode in ("oss", "on_prem"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert "ollama" in model_providers.visible_provider_keys(), mode

    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    assert "ollama" not in model_providers.visible_provider_keys()


def test_shipped_defaults_expose_the_core_providers_everywhere(monkeypatch):
    for mode in ("oss", "on_prem", "saas"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert {"openai", "anthropic", "watsonx"} <= model_providers.visible_provider_keys(), mode


def test_azure_ai_ships_for_on_prem_and_saas(monkeypatch):
    for mode in ("on_prem", "saas"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert "azure_ai" in model_providers.visible_provider_keys(), mode

    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert "azure_ai" not in model_providers.visible_provider_keys()


def test_payload_reports_the_run_mode_it_filtered_on(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    payload = model_providers.provider_visibility_payload()

    assert payload["run_mode"] == "saas"
    assert [entry["name"] for entry in payload["providers"]] == [
        entry["name"] for entry in model_providers.visible_providers()
    ]
    assert all(entry["display_name"] for entry in payload["providers"])


def test_an_unrecognised_run_mode_is_treated_as_oss(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "not-a-mode")
    assert model_providers.visible_provider_keys() == model_providers.visible_provider_keys("oss")


def test_a_missing_mode_key_hides_the_provider(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: openai
    display_name: OpenAI
    modes:
      oss: true
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    assert model_providers.visible_provider_keys() == frozenset()

    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert model_providers.visible_provider_keys() == {"openai"}


def test_a_provider_hidden_in_every_mode_is_omitted_everywhere(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: openai
    modes:
      oss: false
      on_prem: false
      saas: false
""",
        ),
    )
    for mode in ("oss", "on_prem", "saas"):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert model_providers.visible_provider_keys() == frozenset(), mode


def test_flipping_a_mode_in_the_config_needs_no_code_change(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: ollama
    display_name: Ollama
    modes:
      oss: true
      on_prem: true
      saas: true
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    assert "ollama" in model_providers.visible_provider_keys()


def test_a_provider_the_file_omits_is_never_visible(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: openai
    modes:
      oss: true
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert not model_providers.is_provider_visible("groq")
    assert model_providers.is_provider_visible("OpenAI")


def test_names_are_normalised_and_duplicates_drop(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: "  OpenAI  "
    display_name: First
    modes:
      oss: true
  - name: openai
    display_name: Second
    modes:
      oss: true
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert model_providers.visible_provider_entries() == (("openai", "First", (), ()),)


def test_a_non_boolean_mode_value_hides_rather_than_shows(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: openai
    modes:
      oss: maybe
  - name: anthropic
    modes:
      oss: "true"
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert model_providers.visible_provider_keys() == {"anthropic"}


def test_display_name_falls_back_to_the_provider_name(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(tmp_path, "providers:\n  - name: groq\n    modes:\n      oss: true\n"),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert model_providers.visible_provider_entries() == (("groq", "groq", (), ()),)


def test_an_unreadable_override_falls_back_to_the_shipped_file(monkeypatch, tmp_path):
    monkeypatch.setenv(model_providers.CONFIG_PATH_ENV, str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    model_providers.reload()
    shipped = model_providers.visible_provider_keys()

    monkeypatch.delenv(model_providers.CONFIG_PATH_ENV)
    model_providers.reload()
    assert shipped == model_providers.visible_provider_keys()
    assert "openai" in shipped


def test_a_malformed_config_falls_back_rather_than_hiding_everything(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(tmp_path, "providers: not-a-list\n"),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert "openai" in model_providers.visible_provider_keys()


def test_a_row_can_declare_the_models_its_gateway_serves(monkeypatch, tmp_path):
    """A self-hosted OpenAI-compatible endpoint serves ids LiteLLM cannot know."""
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            """
providers:
  - name: openai_like
    display_name: Internal Gateway
    modes:
      oss: true
    models:
      - llama-3.3-70b
      - "  qwen2.5-coder-32b  "
      - llama-3.3-70b
    embedding_models:
      - bge-m3
""",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")

    assert model_providers.visible_provider_entries() == (
        (
            "openai_like",
            "Internal Gateway",
            ("llama-3.3-70b", "qwen2.5-coder-32b"),
            ("bge-m3",),
        ),
    )


def test_a_row_that_declares_no_models_reports_empty_tuples(monkeypatch, tmp_path):
    monkeypatch.setenv(
        model_providers.CONFIG_PATH_ENV,
        _write(
            tmp_path,
            "providers:\n  - name: openai\n    modes:\n      oss: true\n    models: nope\n",
        ),
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    assert model_providers.visible_provider_entries() == (("openai", "openai", (), ()),)
