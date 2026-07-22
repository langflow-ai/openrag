import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  dedupeConsecutiveErrorMessages,
  extractStreamProviderError,
  formatProviderErrorMessage,
  looksLikeProviderErrorContent,
} from "./chat-stream-errors";

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

  it("returns null when the error chunk has no message", () => {
    assert.equal(extractStreamProviderError({ status: "failed" }), null);
    assert.equal(extractStreamProviderError({ finish_reason: "error" }), null);
  });

  it("strips embedded JSON from provider error chunks", () => {
    assert.equal(
      extractStreamProviderError({
        status: "failed",
        error: {
          message:
            'Failed to authenticate with IBM Watson: {"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found."}',
        },
      }),
      "Failed to authenticate with IBM Watson: Provided API key could not be found.",
    );
  });
});

describe("looksLikeProviderErrorContent", () => {
  it("detects watsonx credential dumps streamed as assistant text", () => {
    assert.equal(
      looksLikeProviderErrorContent(
        'Failed to initialize IBM WatsonX embedding model: Error: {"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found."} An error occurred while generating a response.',
      ),
      true,
    );
  });

  it("detects permission-denied style provider errors", () => {
    assert.equal(
      looksLikeProviderErrorContent(
        "Permission denied: model access not authorized.",
      ),
      true,
    );
  });

  it("does not flag ordinary replies", () => {
    assert.equal(
      looksLikeProviderErrorContent("OpenRAG uses Langflow and OpenSearch."),
      false,
    );
    assert.equal(
      looksLikeProviderErrorContent(
        "The docs explain unauthorized access patterns and when permission denied responses appear.",
      ),
      false,
    );
  });

  it("flags the exact generic stream fallback message", () => {
    assert.equal(
      looksLikeProviderErrorContent(
        "An error occurred while generating a response.",
      ),
      true,
    );
  });
});

describe("dedupeConsecutiveErrorMessages", () => {
  it("collapses repeated identical assistant errors", () => {
    const err = {
      role: "assistant",
      content: "Provided API key could not be found.",
      error: true,
    };
    assert.deepEqual(
      dedupeConsecutiveErrorMessages([
        { role: "user", content: "hello" },
        err,
        { ...err },
        { ...err },
      ]),
      [{ role: "user", content: "hello" }, err],
    );
  });
});

describe("formatProviderErrorMessage", () => {
  it("extracts OpenAI-style embedded JSON", () => {
    assert.equal(
      formatProviderErrorMessage(
        'Provider request failed: {"error":{"message":"Incorrect API key provided","type":"invalid_request_error"}}',
      ),
      "Provider request failed: Incorrect API key provided",
    );
  });

  it("strips embedded JSON even with trailing text", () => {
    assert.equal(
      formatProviderErrorMessage(
        'Failed to authenticate. Error: {"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found."} trailing junk',
      ),
      "Failed to authenticate: Provided API key could not be found.",
    );
  });

  it("keeps a readable prefix when JSON is truncated", () => {
    assert.equal(
      formatProviderErrorMessage("Invalid API key {not-valid-json"),
      "Invalid API key",
    );
  });
});
