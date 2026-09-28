import assert from "node:assert/strict";
import { describe, it } from "vitest";
import { getIngestChunkSettingsError } from "./types";

const validSettings = {
  embeddingModel: "prod-embed",
  chunkSize: 1024,
  chunkOverlap: 50,
};

describe("getIngestChunkSettingsError", () => {
  it("blocks ingestion without an explicitly selected embedding model", () => {
    assert.equal(
      getIngestChunkSettingsError({ ...validSettings, embeddingModel: "  " }),
      "Select an embedding model in Settings before ingesting files",
    );
  });

  it("continues validating chunk settings", () => {
    assert.equal(
      getIngestChunkSettingsError({ ...validSettings, chunkSize: 0 }),
      "Chunk size must be at least 1",
    );
    assert.equal(
      getIngestChunkSettingsError({
        ...validSettings,
        chunkSize: 100,
        chunkOverlap: 100,
      }),
      "Chunk overlap must be less than chunk size",
    );
    assert.equal(getIngestChunkSettingsError(validSettings), null);
  });
});
