import assert from "node:assert/strict";
import { describe, it } from "vitest";
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
      "Provided API key is Invalid.",
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

  it("flags IBM disabled API key messages", () => {
    assert.equal(
      looksLikeProviderErrorContent("Provided API key is disabled."),
      true,
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
      "Incorrect API key provided",
    );
  });

  it("strips embedded JSON even with trailing text", () => {
    assert.equal(
      formatProviderErrorMessage(
        'Failed to authenticate. Error: {"errorCode":"BXNIM0415E","errorMessage":"Provided API key could not be found."} trailing junk',
      ),
      "Provided API key is Invalid.",
    );
  });

  it("keeps a readable prefix when JSON is truncated", () => {
    assert.equal(
      formatProviderErrorMessage("Invalid API key {not-valid-json"),
      "Invalid API key",
    );
  });

  it("strips Error <label>: wrappers and prefers nested JSON messages", () => {
    assert.equal(
      formatProviderErrorMessage(
        "Error running graph: Error building Component Language Model: Rate limit exceeded",
      ),
      "Rate limit exceeded",
    );
    assert.equal(
      formatProviderErrorMessage(
        'Error running graph: Error building Component Embedding Model: Failed to authenticate. Error: {"errorCode":"BXNIM0420E","errorMessage":"Provided API key is disabled."}',
      ),
      "Provided API key is disabled.",
    );
    assert.equal(formatProviderErrorMessage("Error: boom"), "Error: boom");
  });

  it("keeps the whole string when the prefix is only a syntactic fragment", () => {
    const body =
      '{"took":2719,"timed_out":false,"total":300,"updated":19,' +
      '"version_conflicts":1,"failures":[{"index":"documents","id":"20",' +
      '"cause":{"type":"version_conflict_engine_exception"}}]}';
    const raw = `ConflictError(409, '${body}')`;
    assert.equal(formatProviderErrorMessage(raw), raw);
  });

  it("still keeps a readable prefix that is a real sentence", () => {
    assert.equal(
      formatProviderErrorMessage("Invalid API key {not-valid-json"),
      "Invalid API key",
    );
  });

  // The OpenAI SDK prints the body as a Python dict, which is how a gateway
  // error reads once Langflow relays it. It used to collapse to "400 -".
  const overflow =
    "watsonx/intfloat/multilingual-e5-large: Invalid input argument for Model " +
    "'intfloat/multilingual-e5-large': This model's maximum context length is 512 " +
    "tokens. However, you requested 548 tokens in the input for embedding generation.";

  it("reads the message out of an OpenAI SDK error printed as a Python dict", () => {
    assert.equal(
      formatProviderErrorMessage(
        `Error code: 400 - {'error': {'message': "${overflow}", 'type': 'invalid_request_error', 'code': 'context_length_exceeded'}}`,
      ),
      overflow,
    );
    assert.equal(
      formatProviderErrorMessage(
        `Error building Component OpenSearch: \n\nError code: 400 - {'error': {'message': "${overflow}", 'type': 'invalid_request_error'}}`,
      ),
      overflow,
    );
  });

  it("unescapes a single-quoted Python message", () => {
    assert.equal(
      formatProviderErrorMessage(
        "Error code: 404 - {'error': {'message': 'The model `x` doesn\\'t exist, said \"the API\"', 'type': 'api_error'}}",
      ),
      'The model `x` doesn\'t exist, said "the API"',
    );
  });

  it("keeps the whole string when the prefix is only a status code", () => {
    const raw = "Error code: 502 - {'error': <object at 0x1>}";
    assert.equal(
      formatProviderErrorMessage(raw),
      "502 - {'error': <object at 0x1>}",
    );
  });

  it("does not read a message out of prose that merely mentions one", () => {
    const raw = "The reply had 'message': 'hello' in it";
    assert.equal(formatProviderErrorMessage(raw), raw);
  });
});
