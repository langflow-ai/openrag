import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  findGroupedSelection,
  groupedCatalogOptions,
  liveModelOption,
  mergeLiveCatalogOptions,
  onboardingCatalogConfigured,
  onboardingCredentialFields,
  providerCredentialsSatisfied,
  savedSecretFieldsForProvider,
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
        { model: "container", mode: "chat" },
        { model: "ft:gpt-3.5-turbo", mode: "chat" },
        { model: "gpt-4o", mode: "chat", capabilities: ["vision"] },
        {
          model: "gpt-4o-mini",
          mode: "chat",
          capabilities: ["function_calling"],
        },
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
      ["gpt-4o-mini", "gpt-4o", "container", "ft:gpt-3.5-turbo"],
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

  it("does not auto-offer LiteLLM template rows ahead of a real chat model", () => {
    const groups = groupedCatalogOptions(catalog, { openai: true }, "language");
    assert.equal(groups[0].options[0].value, "gpt-4o-mini");
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

describe("findGroupedSelection", () => {
  it("disambiguates the same model id across providers", () => {
    const overlap = {
      providers: [
        {
          key: "openai",
          name: "OpenAI",
          models: [{ model: "gpt-4o", mode: "chat" }],
        },
        {
          key: "azure",
          name: "Azure",
          models: [{ model: "gpt-4o", mode: "chat" }],
        },
      ],
    };
    const groups = groupedCatalogOptions(
      overlap,
      { openai: true, azure: true },
      "language",
    );
    const openai = findGroupedSelection(groups, "gpt-4o", "openai");
    const azure = findGroupedSelection(groups, "gpt-4o", "azure");
    assert.equal(openai?.group.key, "openai");
    assert.equal(azure?.group.key, "azure");
    assert.equal(openai?.option?.provider, "openai");
    assert.equal(azure?.option?.provider, "azure");
  });

  it("still resolves by model name when no provider is given", () => {
    const groups = groupedCatalogOptions(
      catalog,
      { openai: true, anthropic: true },
      "language",
    );
    const selected = findGroupedSelection(groups, "claude-sonnet-4-5");
    assert.equal(selected?.group.key, "anthropic");
  });
});

describe("providerCredentialsSatisfied", () => {
  it("reuses a legacy OpenAI key without another paste", () => {
    assert.equal(
      savedSecretFieldsForProvider(
        { openai: { has_api_key: true } },
        "openai",
      ).includes("api_key"),
      true,
    );
    assert.equal(
      providerCredentialsSatisfied(
        { openai: { has_api_key: true, configured: true } },
        "openai",
        catalog,
      ),
      true,
    );
  });

  it("still requires a key when nothing is saved", () => {
    assert.equal(
      providerCredentialsSatisfied(
        { openai: { has_api_key: false } },
        "openai",
        catalog,
      ),
      false,
    );
  });
});

describe("newest models first", () => {
  const provider = (models: Array<{ model: string }>) => ({
    providers: [{ key: "p", name: "P", models, embedding_models: [] }],
  });
  const order = (names: string[]) =>
    groupedCatalogOptions(
      provider(
        names.map((model) => ({ model, capabilities: ["function_calling"] })),
      ),
      undefined,
      "language",
    )[0].options.map((option) => option.value);

  it("ranks by version, newest first", () => {
    assert.deepEqual(order(["gpt-4o", "gpt-3.5-turbo", "gpt-5", "gpt-4.1"]), [
      "gpt-5",
      "gpt-4.1",
      "gpt-4o",
      "gpt-3.5-turbo",
    ]);
  });

  it("puts a bare alias above its own dated snapshot", () => {
    // `gpt-5` and `gpt-5-2025-08-07` are the same model; the alias is the one
    // to offer, so a missing stamp has to rank as newer, not older.
    assert.deepEqual(order(["gpt-5-2025-08-07", "gpt-5"]), [
      "gpt-5",
      "gpt-5-2025-08-07",
    ]);
  });

  it("orders snapshots of one version by their stamp", () => {
    assert.deepEqual(
      order(["claude-opus-4-5-20251101", "claude-opus-4-5-20260401"]),
      ["claude-opus-4-5-20260401", "claude-opus-4-5-20251101"],
    );
  });

  it("falls back to alphabetical when nothing is versioned", () => {
    assert.deepEqual(order(["mistral-large", "granite-instruct"]), [
      "granite-instruct",
      "mistral-large",
    ]);
  });
});

describe("mergeLiveCatalogOptions creates a missing group", () => {
  it("adds watsonx embeddings the bundled table does not carry", () => {
    // LiteLLM lists zero watsonx embedding models, so groupedCatalogOptions
    // drops the group entirely — the live rows are the only ones there are.
    const merged = mergeLiveCatalogOptions(
      [],
      "watsonx",
      [liveModelOption("ibm/slate-125m-english-rtrvr", "watsonx")],
      "IBM watsonx.ai",
    );

    assert.equal(merged.length, 1);
    assert.equal(merged[0].key, "watsonx");
    assert.equal(merged[0].group, "IBM watsonx.ai");
    assert.deepEqual(
      merged[0].options.map((option) => option.value),
      ["ibm/slate-125m-english-rtrvr"],
    );
  });
});
