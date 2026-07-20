import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { extractStreamProviderError } from "./chat-stream-errors";

describe("extractStreamProviderError", () => {
  it("returns null for non-error chunks", () => {
    assert.equal(extractStreamProviderError({ status: "ok" }), null);
    assert.equal(extractStreamProviderError(null), null);
  });

  it("reads error.message from failed provider chunks", () => {
    assert.equal(
      extractStreamProviderError({
        status: "failed",
        finish_reason: "error",
        error: {
          message:
            "Rate limit exceeded for watsonx.ai. Please try again later.",
        },
      }),
      "Rate limit exceeded for watsonx.ai. Please try again later.",
    );
  });

  it("reads string error and top-level message fallbacks", () => {
    assert.equal(
      extractStreamProviderError({
        status: "failed",
        error: "Invalid API key for Anthropic.",
      }),
      "Invalid API key for Anthropic.",
    );
    assert.equal(
      extractStreamProviderError({
        finish_reason: "error",
        message: "Permission denied: model access not authorized.",
      }),
      "Permission denied: model access not authorized.",
    );
  });

  it("returns a default when the error chunk has no message", () => {
    assert.equal(
      extractStreamProviderError({ status: "failed" }),
      "An error occurred while generating a response.",
    );
  });
});
