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
import {
  groupedCatalogOptions,
  pendingDeploymentOptions,
} from "./catalog-models";
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

describe("onboarding, before anything is saved", () => {
  /**
   * The catalogue publishes a deployment-based provider's models from *saved*
   * configuration, so during onboarding it has nothing to offer. Without
   * reading the form, the picker is empty while the operator is looking at
   * the very names it should contain — and they end up typing each name
   * twice, once as a deployment and once as a custom model.
   */
  const TYPED = {
    chat_deployments: "gpt-4.1-nano, prod-chat-east",
    embedding_deployments: "text-embedding-3-small",
    vlm_deployments: "gpt-4.1-nano",
  };

  it("offers the chat deployments the operator just typed", () => {
    const options = pendingDeploymentOptions(TYPED, "azure_ai", "language");
    assert.deepEqual(
      options?.map((option) => option.value),
      ["gpt-4.1-nano", "prod-chat-east"],
    );
    assert.equal(options?.[0].provider, "azure_ai");
  });

  it("keeps embedding deployments in the embedding step", () => {
    assert.deepEqual(
      pendingDeploymentOptions(TYPED, "azure_ai", "embedding")?.map(
        (o) => o.value,
      ),
      ["text-embedding-3-small"],
    );
  });

  it("carries vision through so the capability is not lost before saving", () => {
    const options = pendingDeploymentOptions(TYPED, "azure_ai", "language");
    const vision = options?.find((option) => option.value === "gpt-4.1-nano");
    const plain = options?.find((option) => option.value === "prod-chat-east");
    assert.deepEqual(vision?.model?.capabilities, ["vision"]);
    assert.equal(plain?.model?.capabilities, undefined);
  });

  it("attaches nothing a deployment name does not prove", () => {
    const options = pendingDeploymentOptions(
      { chat_deployments: "gpt-4.1-nano" },
      "azure_ai",
      "language",
    );
    assert.deepEqual(options?.[0].model, {
      model: "gpt-4.1-nano",
      mode: "chat",
    });
  });

  it("accepts commas, newlines and stray whitespace", () => {
    assert.deepEqual(
      pendingDeploymentOptions(
        { chat_deployments: " a , b \n c " },
        "azure_ai",
        "language",
      )?.map((o) => o.value),
      ["a", "b", "c"],
    );
  });

  it("leaves the catalogue in charge for a provider without deployment fields", () => {
    // null, not [] — an empty array would mean "this provider has none".
    assert.equal(
      pendingDeploymentOptions({ api_key: "k" }, "openai", "language"),
      null,
    );
    assert.equal(
      pendingDeploymentOptions(undefined, "openai", "language"),
      null,
    );
  });

  it("returns an empty list, not null, once the fields exist but are blank", () => {
    assert.deepEqual(
      pendingDeploymentOptions(
        { chat_deployments: "" },
        "azure_ai",
        "language",
      ),
      [],
    );
  });
});
