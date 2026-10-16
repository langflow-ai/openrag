"""A provider that owns its model list, and what that must not disturb.

Azure AI Foundry's catalogue listing is of models *available to deploy*, not
models deployed — live validation returned 462 entries all marked `succeeded`
while sampled models were uncallable. LiteLLM's `azure_ai` rows are the same
kind of thing: a price table. So the configured deployments are the whole of
that provider's inventory, and nothing may add to it.

Everything here also guards the blast radius: `_catalog()` is shared, and
shrinking one provider's inventory changes model *ownership*, which
`split_model_id` consults.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config import model_providers
from enhancements.providers.azure import foundry
from enhancements.providers.contracts import CatalogEntry
from enhancements.providers.registry import authoritative_inventory_keys, configured_inventory
from services import model_catalog
from services.llm_gateway import split_model_id


@pytest.fixture(autouse=True)
def _fresh_caches():
    model_providers.reload()
    model_catalog._catalog.cache_clear()
    model_catalog._catalog_for.cache_clear()
    model_catalog._model_owners.cache_clear()
    yield
    model_providers.reload()
    model_catalog._catalog.cache_clear()
    model_catalog._catalog_for.cache_clear()
    model_catalog._model_owners.cache_clear()


def _catalog_with(stored: dict, run_mode: str = "oss", monkeypatch=None):
    """The published catalogue, as it would be for this stored configuration."""
    config = SimpleNamespace(
        providers=SimpleNamespace(
            stored_credentials=lambda key: stored if key == "azure_ai" else {}
        )
    )
    with patch("config.settings.get_openrag_config", lambda: config):
        model_catalog._catalog.cache_clear()
        model_catalog._catalog_for.cache_clear()
        model_catalog._model_owners.cache_clear()
        return {entry["key"]: entry for entry in model_catalog.catalog()["providers"]}


@pytest.fixture
def _foundry_visible(monkeypatch, tmp_path):
    """Foundry is hidden in every shipped run mode; show it to inspect it."""
    config = tmp_path / "providers.yaml"
    config.write_text(
        "providers:\n"
        "  - name: openai\n    display_name: OpenAI\n    modes: {oss: true}\n"
        "  - name: azure\n    display_name: Azure OpenAI\n    modes: {oss: true}\n"
        "  - name: azure_ai\n    display_name: Azure AI Foundry\n    modes: {oss: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv(model_providers.CONFIG_PATH_ENV, str(config))
    model_providers.reload()
    yield


class TestTheInventoryReplacesRatherThanAugments:
    def test_litellm_rows_never_become_selectable_options(self, _foundry_visible) -> None:
        """The regression this whole change exists for.

        Substituting a live list the way an aliased provider does is not
        enough: `_catalog` appends `chat_by_provider[key]` afterwards, and
        `azure_ai` has over a hundred rows there. Measured before the fix: 109
        chat options where one was configured.
        """
        catalog = _catalog_with({"chat_deployments": "prod-chat-east"})

        chat = [entry["model"] for entry in catalog["azure_ai"]["models"]]
        assert chat == ["prod-chat-east"]
        assert "mistral-medium-2505" not in chat

    def test_an_unconfigured_provider_offers_nothing(self, _foundry_visible) -> None:
        """Empty is a real answer, not a reason to fall back.

        `None` would mean "not authoritative"; `()` means "authoritative and
        nothing configured", and the pickers must stay empty.
        """
        catalog = _catalog_with({})

        assert catalog["azure_ai"]["models"] == []
        assert catalog["azure_ai"]["embedding_models"] == []

    def test_the_provider_still_appears_so_it_can_be_configured(self, _foundry_visible) -> None:
        """An empty inventory must not remove the provider from Settings."""
        catalog = _catalog_with({})

        assert catalog["azure_ai"]["name"] == "Azure AI Foundry"
        assert catalog["azure_ai"]["credential_fields"]

    def test_chat_and_embedding_lists_stay_separate(self, _foundry_visible) -> None:
        catalog = _catalog_with(
            {"chat_deployments": "prod-chat", "embedding_deployments": "prod-embed"}
        )

        assert [e["model"] for e in catalog["azure_ai"]["models"]] == ["prod-chat"]
        assert [e["model"] for e in catalog["azure_ai"]["embedding_models"]] == ["prod-embed"]

    def test_exclusions_still_apply_last(self, monkeypatch, tmp_path) -> None:
        """An operator who suppresses an id means it, wherever it came from."""
        config = tmp_path / "providers.yaml"
        config.write_text(
            "providers:\n"
            "  - name: azure_ai\n    display_name: Azure AI Foundry\n"
            "    modes: {oss: true}\n    exclude_models:\n      - retired-*\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
        monkeypatch.setenv(model_providers.CONFIG_PATH_ENV, str(config))
        model_providers.reload()

        catalog = _catalog_with({"chat_deployments": "prod-chat, retired-chat"})

        assert [e["model"] for e in catalog["azure_ai"]["models"]] == ["prod-chat"]


class TestTheSourceOfTheListIsPublished:
    """An empty list means opposite things depending on where it came from.

    LiteLLM-derived and empty means the provider serves none of that kind.
    Configuration-derived and empty means the operator has named none yet —
    which is exactly the state they are in while configuring it. A caller that
    cannot tell them apart hides the provider at the step where it would be
    set up.
    """

    def test_an_authoritative_provider_says_its_list_is_configured(self, _foundry_visible) -> None:
        catalog = _catalog_with({"chat_deployments": "prod-chat"})
        assert catalog["azure_ai"]["inventory_source"] == "configured"

    def test_it_says_so_even_when_nothing_is_configured(self, _foundry_visible) -> None:
        """The case that matters: empty, and not because it serves none."""
        catalog = _catalog_with({})
        assert catalog["azure_ai"]["inventory_source"] == "configured"
        assert catalog["azure_ai"]["embedding_models"] == []

    def test_every_other_provider_reports_the_catalogue(self, _foundry_visible) -> None:
        catalog = _catalog_with({})
        assert catalog["openai"]["inventory_source"] == "catalog"
        assert catalog["azure"]["inventory_source"] == "catalog"


class TestVisionSurvivesToThePicker:
    def test_a_vision_deployment_carries_the_capability(self, _foundry_visible) -> None:
        """The whole point of the structured inventory.

        `ProviderEntry.models` is a tuple of strings, so the path an aliased
        provider uses would drop this.
        """
        catalog = _catalog_with(
            {"chat_deployments": "prod-chat, vision-primary", "vlm_deployments": "vision-primary"}
        )

        by_name = {e["model"]: e for e in catalog["azure_ai"]["models"]}
        assert by_name["vision-primary"]["capabilities"] == ["vision"]
        assert "capabilities" not in by_name["prod-chat"]

    def test_the_vision_picker_sees_exactly_the_marked_deployments(self, _foundry_visible) -> None:
        """Mirrors the frontend filter: chat entries whose capabilities include vision."""
        catalog = _catalog_with(
            {
                "chat_deployments": "a, b, c",
                "vlm_deployments": "b",
            }
        )

        vision = [
            e["model"]
            for e in catalog["azure_ai"]["models"]
            if "vision" in (e.get("capabilities") or [])
        ]
        assert vision == ["b"]

    def test_a_vision_deployment_is_one_entry_not_two(self, _foundry_visible) -> None:
        """Vision annotates a chat deployment; it is not a second inventory."""
        catalog = _catalog_with({"chat_deployments": "shared", "vlm_deployments": "shared"})

        assert [e["model"] for e in catalog["azure_ai"]["models"]] == ["shared"]

    def test_a_vision_only_name_adds_nothing(self) -> None:
        """It is rejected at save time rather than silently inventing a chat model."""
        inventory = foundry.configured_inventory({"chat_deployments": "a", "vlm_deployments": "b"})

        assert [e.model for e in inventory] == ["a"]
        assert foundry.unlisted_vlm_deployments(
            {"chat_deployments": "a", "vlm_deployments": "b"}
        ) == ("b",)


class TestNothingIsInferredFromTheName:
    @pytest.mark.parametrize("name", ["gpt-4.1-nano", "gpt-6-luna", "Phi-4"])
    def test_a_deployment_named_after_a_model_gains_none_of_its_metadata(
        self, _foundry_visible, name
    ) -> None:
        """A Foundry deployment name is an operator's alias.

        Naming one `gpt-6-luna` is no evidence that the model behind it is
        gpt-6-luna, so attaching that row's context window, pricing or tool
        support would be a guess rendered as fact in the details panel.
        """
        catalog = _catalog_with({"chat_deployments": name})

        entry = catalog["azure_ai"]["models"][0]
        assert entry == {"model": name, "mode": "chat"}
        assert "capabilities" not in entry
        assert "input_cost_per_token" not in entry
        assert "max_input_tokens" not in entry


class TestOwnershipAndRoutingAreNotCollateralDamage:
    """Shrinking one provider's inventory changes `catalog_owner`.

    `split_model_id` consults it for slash-shaped ids, so this is where a
    regression would land — most consequentially between the two Azure rows.
    """

    def test_a_foundry_id_still_resolves_to_foundry(self, _foundry_visible) -> None:
        _catalog_with({"chat_deployments": "prod-chat-east"})
        assert split_model_id("azure_ai:prod-chat-east") == ("azure_ai", "prod-chat-east")

    def test_an_azure_openai_id_is_untouched(self, _foundry_visible) -> None:
        _catalog_with({"chat_deployments": "prod-chat-east"})
        assert split_model_id("azure:gpt-4.1") == ("azure", "gpt-4.1")

    def test_azure_openai_keeps_its_full_catalogue(self, _foundry_visible) -> None:
        """Only the authoritative provider shrinks."""
        catalog = _catalog_with({"chat_deployments": "prod-chat-east"})

        azure = {e["model"] for e in catalog["azure"]["models"]}
        assert "gpt-4.1" in azure
        assert len(azure) > 10

    def test_a_legacy_slash_form_foundry_id_still_splits(self, _foundry_visible) -> None:
        """`azure_ai/Phi-4` no longer has a catalogue owner, and must still route.

        Ownership lookup misses now that Foundry publishes only configured
        deployments, so resolution falls through to the provider-prefix branch
        — which is the behaviour stored ids from before this change rely on.
        """
        _catalog_with({"chat_deployments": "prod-chat-east"})
        assert split_model_id("azure_ai/Phi-4") == ("azure_ai", "Phi-4")

    def test_a_model_both_azure_rows_served_is_not_misrouted(self, _foundry_visible) -> None:
        """The two Azure providers are not interchangeable.

        With Foundry no longer claiming catalogue ids, an id both rows listed
        must still resolve to whichever one the caller named.
        """
        _catalog_with({"chat_deployments": "prod-chat-east"})
        assert split_model_id("azure:gpt-6-luna") == ("azure", "gpt-6-luna")
        assert split_model_id("azure_ai:gpt-6-luna") == ("azure_ai", "gpt-6-luna")

    def test_other_providers_are_entirely_unaffected(self, _foundry_visible) -> None:
        catalog = _catalog_with({"chat_deployments": "prod-chat-east"})

        assert len(catalog["openai"]["models"]) > 10
        assert any(e["model"].startswith("gpt-") for e in catalog["openai"]["models"])


class TestTheContract:
    def test_foundry_declares_itself_authoritative(self) -> None:
        assert "azure_ai" in authoritative_inventory_keys()

    def test_no_other_provider_does(self) -> None:
        """Every other provider keeps exactly its existing behaviour."""
        assert authoritative_inventory_keys() == frozenset({"azure_ai"})

    def test_the_registry_returns_none_for_a_non_authoritative_provider(self) -> None:
        """`None` is what leaves the catalogue on its normal path."""
        assert configured_inventory("watsonx_onprem", {"api_base": "https://x"}) is None
        assert configured_inventory("openai", {}) is None

    def test_the_contract_type_is_hashable(self) -> None:
        """It goes in the catalogue's lru_cache key, so a dict would not do."""
        entry = CatalogEntry(model="m", mode="chat", capabilities=("vision",))
        assert hash((entry,))
        assert entry.capabilities == ("vision",)

    def test_the_contract_module_imports_nothing_from_the_package(self) -> None:
        """`registry` imports the provider modules, so a type defined there
        and imported back by a provider would be circular."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "enhancements/providers/contracts.py"
        )
        text = source.read_text(encoding="utf-8")
        for forbidden in (
            "from enhancements",
            "import enhancements",
            "from config",
            "from services",
        ):
            assert forbidden not in text, forbidden


class TestDeploymentParsing:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("a, b", ("a", "b")),
            ("a\nb", ("a", "b")),
            ("  a  ,  b  ", ("a", "b")),
            ("a, a, b", ("a", "b")),
            ("", ()),
            (None, ()),
        ],
    )
    def test_names_accept_what_people_paste(self, raw, expected) -> None:
        assert foundry.chat_deployments({"chat_deployments": raw}) == expected

    def test_order_is_preserved(self) -> None:
        assert foundry.chat_deployments({"chat_deployments": "z, a, m"}) == ("z", "a", "m")


class TestFirstReleaseEndpointPolicy:
    """Only the surface validated end to end is offered for new configuration."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_base",
        [
            "https://r.services.ai.azure.com/api/projects/p/openai/v1",
            "https://r.services.ai.azure.com/models",
            "https://r.services.ai.azure.com",
        ],
    )
    async def test_unvalidated_surfaces_are_refused_for_a_new_save(
        self, monkeypatch, api_base
    ) -> None:
        def _no_calls(**_kw):
            raise AssertionError("must fail before reaching the network")

        monkeypatch.setattr("httpx.AsyncClient", _no_calls)

        with pytest.raises(foundry.UnsupportedEndpointError, match="/openai/v1"):
            await foundry.lightweight_health_check({"api_base": api_base, "api_key": "k"})

    @pytest.mark.parametrize(
        "api_base, expected_route",
        [
            ("https://r.services.ai.azure.com/api/projects/p/openai/v1", "hosted_vllm"),
            ("https://r.services.ai.azure.com/models", "azure_ai"),
            ("https://r.services.ai.azure.com", "azure_ai"),
        ],
    )
    def test_their_routing_is_retained_for_a_configuration_already_saved(
        self, api_base, expected_route
    ) -> None:
        """Refused at save time, still routed — so nothing already configured
        breaks, and admitting a surface later is one constant."""
        assert foundry.litellm_route({"api_base": api_base}) == expected_route

    @pytest.mark.asyncio
    async def test_a_vision_name_missing_from_chat_is_refused_with_its_name(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "httpx.AsyncClient", lambda **_kw: pytest.fail("should not reach the network")
        )

        with pytest.raises(ValueError, match="vision-only"):
            await foundry.lightweight_health_check(
                {
                    "api_base": "https://r.services.ai.azure.com/openai/v1",
                    "api_key": "k",
                    "chat_deployments": "prod-chat",
                    "vlm_deployments": "vision-only",
                }
            )
