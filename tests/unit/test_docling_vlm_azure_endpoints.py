"""Azure and Azure AI Foundry VLM endpoints handed to docling-serve.

docling-serve calls the model endpoint itself using the `picture_description_api`
block built here, so the URL has to be right for the surface the operator
configured and the credential must not escape into logs or error text.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.docling_service import (  # noqa: E402
    DoclingServeError,
    DoclingService,
    strip_provider_prefix,
)

RESOURCE = "https://contoso.services.ai.azure.com"
SECRET = "super-secret-api-key"


class TestStripProviderPrefix:
    """`:` is canonical; `/` is the legacy form. Only `/` used to be stripped."""

    @pytest.mark.parametrize(
        "model, provider, expected",
        [
            # The bug: a canonical id kept its prefix and was sent as a model
            # name no deployment has.
            ("azure_ai:gpt-4o", "azure_ai", "gpt-4o"),
            ("azure:my-vision", "azure", "my-vision"),
            # The legacy form kept working.
            ("azure_ai/gpt-4o", "azure_ai", "gpt-4o"),
            ("azure/my-vision", "azure", "my-vision"),
            # Already bare: the usual case, since provider and model are
            # separate config fields.
            ("gpt-4o", "azure_ai", "gpt-4o"),
            # A different provider's tag is part of the name, not a prefix.
            ("openai:gpt-4o", "azure_ai", "openai:gpt-4o"),
            # Case-insensitive on the tag, never on the model.
            ("Azure_AI:GPT-4o", "azure_ai", "GPT-4o"),
            ("", "azure_ai", ""),
        ],
    )
    def test_both_separators_are_stripped(self, model, provider, expected) -> None:
        assert strip_provider_prefix(model, provider) == expected

    def test_only_the_first_prefix_goes(self) -> None:
        """A deployment may legitimately contain a colon."""
        assert strip_provider_prefix("azure_ai:team:vision-v2", "azure_ai") == "team:vision-v2"


def _service_with(provider: str, credentials: dict, vlm_model: str) -> tuple:
    """A DoclingService and the config its VLM branch will read."""
    knowledge = SimpleNamespace(
        ocr=False,
        table_structure=False,
        picture_descriptions=True,
        vlm_enabled=True,
        vlm_provider=provider,
        vlm_model=vlm_model,
        vlm_prompt="describe",
        vlm_max_tokens=100,
        vlm_watsonx_api_version="2024-01-01",
        ocr_languages=[],
    )
    providers = SimpleNamespace(credential_values=lambda _key, **_kw: dict(credentials))
    return DoclingService(), SimpleNamespace(knowledge=knowledge, providers=providers)


async def _options(monkeypatch, provider: str, credentials: dict, vlm_model: str) -> dict:
    service, config = _service_with(provider, credentials, vlm_model)
    monkeypatch.setattr("services.docling_service.get_openrag_config", lambda: config)
    return await service._build_docling_options_async()


class TestFoundryEndpointShapes:
    """The chat URL follows the surface, rather than assuming one."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_base, expected_url",
        [
            # OpenAI-compatible surface: inference hangs directly off it.
            (f"{RESOURCE}/openai/v1", f"{RESOURCE}/openai/v1/chat/completions"),
            (f"{RESOURCE}/openai/v1/", f"{RESOURCE}/openai/v1/chat/completions"),
            (
                f"{RESOURCE}/api/projects/p1/openai/v1",
                f"{RESOURCE}/api/projects/p1/openai/v1/chat/completions",
            ),
            # Legacy surface, named explicitly.
            (f"{RESOURCE}/models", f"{RESOURCE}/models/chat/completions"),
            # Legacy surface given as the resource root: `/models` is where
            # inference lives, and is what the gateway targets for the same
            # configuration.
            (RESOURCE, f"{RESOURCE}/models/chat/completions"),
        ],
    )
    async def test_the_url_matches_the_configured_surface(
        self, monkeypatch, api_base, expected_url
    ) -> None:
        options = await _options(
            monkeypatch, "azure_ai", {"api_base": api_base, "api_key": SECRET}, "gpt-4o"
        )
        assert options["picture_description_api"]["url"] == expected_url

    @pytest.mark.asyncio
    async def test_api_version_is_added_only_on_the_dated_legacy_api(self, monkeypatch) -> None:
        legacy = await _options(
            monkeypatch,
            "azure_ai",
            {"api_base": f"{RESOURCE}/models", "api_key": SECRET, "api_version": "2024-05-01"},
            "gpt-4o",
        )
        assert legacy["picture_description_api"]["url"].endswith("?api-version=2024-05-01")

        v1 = await _options(
            monkeypatch,
            "azure_ai",
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": SECRET, "api_version": "2024-05-01"},
            "gpt-4o",
        )
        assert "api-version" not in v1["picture_description_api"]["url"]

    @pytest.mark.asyncio
    async def test_a_pasted_call_path_does_not_double_up(self, monkeypatch) -> None:
        options = await _options(
            monkeypatch,
            "azure_ai",
            {"api_base": f"{RESOURCE}/openai/v1/chat/completions", "api_key": SECRET},
            "gpt-4o",
        )
        assert options["picture_description_api"]["url"] == f"{RESOURCE}/openai/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_an_unrecognised_endpoint_is_refused(self, monkeypatch) -> None:
        with pytest.raises(DoclingServeError, match="/openai/v1"):
            await _options(
                monkeypatch,
                "azure_ai",
                {"api_base": f"{RESOURCE}/anthropic/v1", "api_key": SECRET},
                "gpt-4o",
            )

    @pytest.mark.asyncio
    async def test_a_cleartext_endpoint_is_refused(self, monkeypatch) -> None:
        with pytest.raises(DoclingServeError, match="HTTPS"):
            await _options(
                monkeypatch,
                "azure_ai",
                {"api_base": "http://contoso.services.ai.azure.com/openai/v1", "api_key": SECRET},
                "gpt-4o",
            )


class TestSeparatorReachesTheWire:
    """The separator fix, asserted where it matters: the model sent upstream."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("vlm_model", ["azure_ai:gpt-4o", "azure_ai/gpt-4o", "gpt-4o"])
    async def test_foundry_sends_the_bare_deployment_name(self, monkeypatch, vlm_model) -> None:
        options = await _options(
            monkeypatch,
            "azure_ai",
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": SECRET},
            vlm_model,
        )
        assert options["picture_description_api"]["params"]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("vlm_model", ["azure:my-vision", "azure/my-vision", "my-vision"])
    async def test_azure_openai_sends_the_bare_deployment_name(
        self, monkeypatch, vlm_model
    ) -> None:
        options = await _options(
            monkeypatch,
            "azure",
            {"api_base": "https://contoso.openai.azure.com", "api_key": SECRET},
            vlm_model,
        )
        api = options["picture_description_api"]
        assert api["params"]["model"] == "my-vision"
        # The deployment is also in the path, so a stale prefix broke the URL too.
        assert "/openai/deployments/my-vision/chat/completions" in api["url"]


class TestTheCredentialDoesNotEscape:
    """docling-serve is given the key; nothing else may be.

    The options dict carries the credential in `headers`, so an error or log
    line that echoes it leaks the key.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provider, credentials",
        [
            ("azure_ai", {"api_base": f"{RESOURCE}/anthropic/v1", "api_key": SECRET}),
            (
                "azure_ai",
                {"api_base": "http://contoso.services.ai.azure.com/openai/v1", "api_key": SECRET},
            ),
            ("azure", {"api_base": "http://contoso.openai.azure.com", "api_key": SECRET}),
            ("azure_ai", {"api_base": "", "api_key": SECRET}),
        ],
    )
    async def test_no_rejection_message_contains_the_key(
        self, monkeypatch, provider, credentials
    ) -> None:
        with pytest.raises(DoclingServeError) as exc:
            await _options(monkeypatch, provider, credentials, "gpt-4o")

        assert SECRET not in str(exc.value)
        assert SECRET not in repr(exc.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["azure_ai", "azure"])
    async def test_building_the_options_logs_nothing_containing_the_key(
        self, monkeypatch, provider
    ) -> None:
        """Including the normalization debug line the Foundry branch triggers."""
        records: list[str] = []

        class _Recorder:
            def __getattr__(self, _name):
                def _log(message="", **fields):
                    records.append(f"{message} {fields}")

                return _log

        monkeypatch.setattr("services.docling_service.logger", _Recorder())
        from enhancements.providers.azure import foundry

        monkeypatch.setattr(foundry, "logger", _Recorder())

        api_base = (
            f"{RESOURCE}/openai/v1/chat/completions?api-version=2024-05-01"
            if provider == "azure_ai"
            else "https://contoso.openai.azure.com"
        )
        options = await _options(
            monkeypatch, provider, {"api_base": api_base, "api_key": SECRET}, "gpt-4o"
        )

        # The key is in the options, which is the whole point of the block...
        assert options["picture_description_api"]["headers"]["api-key"] == SECRET
        # ...and nowhere in anything that was logged.
        assert SECRET not in " ".join(records)

    @pytest.mark.asyncio
    async def test_the_credential_is_passed_to_docling_serve_deliberately(
        self, monkeypatch
    ) -> None:
        """Pinning the trust boundary rather than leaving it implicit.

        docling-serve calls the model endpoint directly with these headers, so
        it holds the provider key for the life of the conversion. Any change
        that stops sending it, or starts sending something longer-lived, is a
        change to that boundary and should fail here first.
        """
        options = await _options(
            monkeypatch,
            "azure_ai",
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": SECRET},
            "gpt-4o",
        )
        api = options["picture_description_api"]

        assert api["headers"] == {"api-key": SECRET}
        # API key only for now: no bearer plumbing until Entra is wired
        # end to end, with acquisition, refresh and propagation.
        assert "Authorization" not in api["headers"]
