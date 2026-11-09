import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { knowledgeToIngestSettings } from "./ingest-settings-knowledge";

describe("knowledgeToIngestSettings", () => {
  it("preserves the required empty Azure deployment choice", () => {
    const settings = knowledgeToIngestSettings({
      embedding_provider: "azure",
      embedding_model: "",
    });

    assert.equal(settings.embeddingModel, "");
  });

  it("keeps the legacy default for providers with stable model IDs", () => {
    const settings = knowledgeToIngestSettings({
      embedding_provider: "openai",
      embedding_model: "",
    });

    assert.equal(settings.embeddingModel, "text-embedding-3-small");
  });

  it("uses the explicit trimmed Azure deployment name", () => {
    const settings = knowledgeToIngestSettings({
      embedding_provider: "azure",
      embedding_model: "  prod-embed-eastus  ",
    });

    assert.equal(settings.embeddingModel, "prod-embed-eastus");
  });
});
