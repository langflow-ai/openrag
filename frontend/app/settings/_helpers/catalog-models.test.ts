import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  groupedCatalogOptions,
  mergeLiveCatalogOptions,
  onboardingCatalogConfigured,
  onboardingCredentialFields,
} from "./catalog-models";

const catalog = {
  providers: [
    {
      key: "openai",
      name: "OpenAI",
      credential_fields: [
        {
          key: "api_base",
          label: "API Base",
          required: false,
          field_type: "text",
        },
        {
          key: "organization",
          label: "OpenAI Organization ID",
          required: false,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "OpenAI API Key",
          required: true,
          field_type: "password",
        },
      ],
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
      credential_fields: [
        {
          key: "api_key",
          label: "API Key",
          required: false,
          field_type: "password",
        },
      ],
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

  it("supports arbitrary configured LiteLLM providers", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: true, gemini: true },
      "language",
    );
    assert.deepEqual(
      groups.map((g) => g.key),
      ["openai", "anthropic", "gemini"],
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

  it("keeps empty groups when includeEmpty is set", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: true },
      "embedding",
      { includeEmpty: true },
    );
    assert.deepEqual(
      groups.map((g) => g.key),
      ["openai", "anthropic"],
    );
    assert.equal(groups[1].options.length, 0);
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

describe("onboardingCatalogConfigured", () => {
  it("does not filter the full onboarding catalogue", () => {
    assert.equal(onboardingCatalogConfigured(true, true), undefined);
  });
});

describe("onboardingCredentialFields", () => {
  it("returns the complete provider field schema", () => {
    const fields = onboardingCredentialFields(catalog, "openai");
    assert.deepEqual(
      fields.map((field) => field.key),
      ["api_base", "organization", "api_key"],
    );
    assert.equal(fields[2].required, true);
  });

  it("preserves LiteLLM required flags", () => {
    const fields = onboardingCredentialFields(catalog, "anthropic");
    assert.equal(fields[0].key, "api_key");
    assert.equal(fields[0].required, false);
  });

  it("falls back to generic key and base fields for an unknown provider", () => {
    const fields = onboardingCredentialFields(catalog, "ollama");
    assert.deepEqual(
      fields.map((field) => field.key),
      ["api_key", "api_base"],
    );
  });
});

describe("mergeLiveCatalogOptions", () => {
  it("appends live rows the catalogue does not already list", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true },
      "embedding",
    );
    const merged = mergeLiveCatalogOptions(groups, "openai", [
      {
        value: "text-embedding-3-small",
        label: "text-embedding-3-small",
        provider: "openai",
      },
      { value: "nomic-embed", label: "nomic-embed", provider: "openai" },
    ]);
    assert.deepEqual(
      merged[0].options.map((option) => option.value),
      ["text-embedding-3-small", "nomic-embed"],
    );
  });
});
