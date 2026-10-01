/**
 * Pickers for a provider whose models are its own deployments.
 *
 * Azure AI Foundry's catalogue lists models available to deploy rather than
 * models deployed, so the backend publishes only the operator's configured
 * deployments. These pin what the frontend does with that: the vision filter
 * reads a capability the backend states explicitly, and an empty list is
 * explained rather than reported as a fault.
 */

import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { groupedCatalogOptions } from "./catalog-models";
import { emptyGroupMessage } from "./model-selector";

/** Exactly what the backend publishes for a configured Foundry provider. */
const CATALOG = {
  providers: [
    {
      key: "azure_ai",
      name: "Azure AI Foundry",
      models: [
        { model: "prod-chat-east", mode: "chat" },
        { model: "vision-primary", mode: "chat", capabilities: ["vision"] },
        { model: "vision-lookalike", mode: "chat" },
      ],
      embedding_models: [{ model: "prod-embed", mode: "embedding" }],
      credential_fields: [],
    },
  ],
} as never;

const CONFIGURED = { azure_ai: true };

function models(kind: "language" | "embedding" | "vision"): string[] {
  return groupedCatalogOptions(CATALOG, CONFIGURED, kind).flatMap((group) =>
    group.options.map((option) => option.value),
  );
}

describe("vision capability survives to the picker", () => {
  it("shows only deployments the backend marked vision-capable", () => {
    assert.deepEqual(models("vision"), ["vision-primary"]);
  });

  it("does not infer vision from a deployment name", () => {
    // `vision-lookalike` is named suggestively and carries no capability, so
    // it must not appear. A Foundry deployment name is an operator's alias.
    assert.equal(models("vision").includes("vision-lookalike"), false);
  });

  it("keeps a vision deployment in the language picker too", () => {
    // One entry carrying a capability, not two separate entries.
    assert.deepEqual(models("language").sort(), [
      "prod-chat-east",
      "vision-lookalike",
      "vision-primary",
    ]);
  });

  it("keeps embedding deployments in their own picker", () => {
    assert.deepEqual(models("embedding"), ["prod-embed"]);
    assert.equal(models("language").includes("prod-embed"), false);
    assert.equal(models("vision").includes("prod-embed"), false);
  });
});

describe("an authoritative provider with nothing configured", () => {
  const EMPTY = {
    providers: [
      {
        key: "azure_ai",
        name: "Azure AI Foundry",
        models: [],
        embedding_models: [],
        credential_fields: [],
      },
    ],
  } as never;

  it("offers no models rather than falling back to a catalogue", () => {
    assert.deepEqual(
      groupedCatalogOptions(EMPTY, CONFIGURED, "language", {
        includeEmpty: true,
      }),
      [{ key: "azure_ai", group: "Azure AI Foundry", options: [] }],
    );
  });

  it("explains that deployments have to be listed", () => {
    // "No models available" alone reads as a fault when the provider is in
    // fact fully configured and simply has no deployment names entered.
    assert.match(emptyGroupMessage("azure_ai"), /deployment names/i);
  });

  it("says the same for Azure OpenAI, whose models are also deployments", () => {
    assert.match(emptyGroupMessage("azure"), /deployment names/i);
  });

  it("leaves the generic message for every other provider", () => {
    assert.match(emptyGroupMessage("openai"), /custom model/i);
    assert.match(emptyGroupMessage(undefined), /custom model/i);
  });
});
