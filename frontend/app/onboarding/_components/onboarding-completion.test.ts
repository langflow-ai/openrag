import assert from "node:assert/strict";
import { describe, it } from "node:test";
// Node's built-in TypeScript runner requires the extension; tsc resolves the same source.
// @ts-expect-error TS5097
import { canCompleteOnboarding } from "./onboarding-completion.ts";

describe("canCompleteOnboarding", () => {
  it("allows language-model setup when a model is selected, regardless of Docling health", () => {
    assert.equal(
      canCompleteOnboarding({
        isEmbedding: false,
        llmModel: "gpt-4.1",
        embeddingModel: "",
      }),
      true,
    );
  });

  it("requires a model for the onboarding step being completed", () => {
    assert.equal(
      canCompleteOnboarding({
        isEmbedding: false,
        llmModel: "",
        embeddingModel: "text-embedding-3-small",
      }),
      false,
    );
    assert.equal(
      canCompleteOnboarding({
        isEmbedding: true,
        llmModel: "gpt-4.1",
        embeddingModel: "",
      }),
      false,
    );
  });
});
