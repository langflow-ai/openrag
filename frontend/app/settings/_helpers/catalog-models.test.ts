import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { groupedCatalogOptions } from "./catalog-models";

const catalog = {
  providers: [
    {
      key: "openai",
      name: "OpenAI",
      credential_fields: [],
      model_placeholder: "gpt-4o",
      models: [
        { model: "gpt-4o", mode: "chat", capabilities: ["vision"] },
        { model: "gpt-4o-mini", mode: "chat" },
      ],
      embedding_models: [
        { model: "text-embedding-3-small", mode: "embedding" },
      ],
    },
    {
      key: "anthropic",
      name: "Anthropic",
      credential_fields: [],
      model_placeholder: "claude-sonnet-4-5",
      models: [
        {
          model: "claude-sonnet-4-5",
          mode: "chat",
          capabilities: ["vision"],
        },
      ],
      embedding_models: [],
    },
    {
      key: "gemini",
      name: "Gemini",
      credential_fields: [],
      model_placeholder: "gemini-pro",
      models: [{ model: "gemini-pro", mode: "chat" }],
      embedding_models: [],
    },
  ],
};

describe("groupedCatalogOptions", () => {
  it("keeps only configured OpenRAG providers", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: false },
      "language",
    );
    assert.deepEqual(
      groups.map((g) => g.key),
      ["openai"],
    );
    assert.deepEqual(
      groups[0].options.map((o) => o.value),
      ["gpt-4o", "gpt-4o-mini"],
    );
    assert.equal(groups[0].options[0].provider, "openai");
  });

  it("does not surface LiteLLM providers OpenRAG cannot credential", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: true },
      "language",
    );
    assert.deepEqual(
      groups.map((g) => g.key),
      ["openai", "anthropic"],
    );
  });

  it("uses embedding_models for the ingest picker", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: true },
      "embedding",
    );
    assert.equal(groups.length, 1);
    assert.equal(groups[0].options[0].value, "text-embedding-3-small");
  });

  it("filters vision-capable chat models for the VLM picker", () => {
    const groups = groupedCatalogOptions(catalog, { openai: true }, "vision");
    assert.deepEqual(
      groups[0].options.map((o) => o.value),
      ["gpt-4o"],
    );
  });

  it("returns nothing when the catalogue has not loaded", () => {
    assert.deepEqual(
      groupedCatalogOptions(undefined, { openai: true }, "language"),
      [],
    );
  });
});
