import assert from "node:assert/strict";
import { HttpResponse, http } from "msw";
import { describe, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createTestQueryClient } from "@/test-utils/render";
import {
  canCompleteOnboarding,
  fetchEditedForRollbackCheck,
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

describe("fetchEditedForRollbackCheck", () => {
  it("returns the freshly-fetched edited flag rather than a stale fallback", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({ edited: true })),
    );
    const queryClient = createTestQueryClient();
    // Seed the cache with a stale pre-submission snapshot to prove the
    // fresh fetch (not this cached value) wins.
    queryClient.setQueryData(["settings"], { edited: false });

    const result = await fetchEditedForRollbackCheck(queryClient, false);

    assert.equal(result, true);
  });

  it("falls back to the provided value when the fetch fails", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({}, { status: 500 })),
    );
    const queryClient = createTestQueryClient();

    const result = await fetchEditedForRollbackCheck(queryClient, true);

    assert.equal(result, true);
  });
});
