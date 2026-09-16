import assert from "node:assert/strict";
import { describe, it } from "vitest";
import {
  canCompleteOnboarding,
  shouldRollbackFailedOnboarding,
} from "./onboarding-completion.ts";

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

describe("shouldRollbackFailedOnboarding", () => {
  it("does not roll back an initial validation failure with no saved config", () => {
    assert.equal(shouldRollbackFailedOnboarding(false), false);
    assert.equal(shouldRollbackFailedOnboarding(undefined), false);
  });

  it("rolls back a failed update to an existing onboarding config", () => {
    assert.equal(shouldRollbackFailedOnboarding(true), true);
  });
});
