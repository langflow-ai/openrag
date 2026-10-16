"""Shared, dependency-neutral types for the provider-enhancement contract.

Deliberately imports nothing from this package or from OpenRAG. `registry`
imports the provider modules, and the provider modules need these types, so
anything defined in `registry` would be circular. The catalogue layer reads
them too.

Keep everything here lightweight and **hashable**: `services.model_catalog`
keys an `lru_cache` on the provider entries that carry these, so a type that
cannot go in a tuple key would make a configuration change serve a stale
catalogue.
"""

from __future__ import annotations

from typing import NamedTuple


class CatalogEntry(NamedTuple):
    """One selectable model a provider declares as its own inventory.

    `mode` is `"chat"` or `"embedding"` and decides which picker the entry
    belongs to. `capabilities` carries only what is *known*, which for an
    operator-configured deployment means only what configuration stated —
    `("vision",)` for one marked as a vision deployment, and `()` otherwise.

    Nothing here may be inferred from the model name. An Azure AI Foundry
    deployment name is an operator-chosen alias, so a deployment called
    `gpt-4.1-nano` is not evidence that the model behind it is gpt-4.1-nano,
    and attaching that model's context window or pricing to it would be a
    guess presented as fact.
    """

    model: str
    mode: str
    capabilities: tuple[str, ...] = ()
