import { describe, expect, it } from "vitest";
import { getIngestChunkSettingsError } from "./types";

describe("getIngestChunkSettingsError", () => {
  it("returns null for valid settings", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 1024, chunkOverlap: 50 }),
    ).toBeNull();
  });

  it("returns null when overlap is 0", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 1024, chunkOverlap: 0 }),
    ).toBeNull();
  });

  it("returns null when overlap is exactly chunkSize - 1 (boundary)", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 1024, chunkOverlap: 1023 }),
    ).toBeNull();
  });

  it("returns chunk size error when chunkSize is 0", () => {
    expect(getIngestChunkSettingsError({ chunkSize: 0, chunkOverlap: 0 })).toBe(
      "Chunk size must be at least 1",
    );
  });

  it("returns chunk size error when chunkSize is negative", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: -5, chunkOverlap: 0 }),
    ).toBe("Chunk size must be at least 1");
  });

  it("returns overlap error when chunkOverlap equals chunkSize", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 100, chunkOverlap: 100 }),
    ).toBe("Chunk overlap must be less than chunk size");
  });

  it("returns overlap error when chunkOverlap exceeds chunkSize", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 100, chunkOverlap: 200 }),
    ).toBe("Chunk overlap must be less than chunk size");
  });

  it("chunk size error takes priority when both would fire (size=0, overlap=999)", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 0, chunkOverlap: 999 }),
    ).toBe("Chunk size must be at least 1");
  });

  it("returns null for minimum valid config (chunkSize: 1, chunkOverlap: 0)", () => {
    expect(
      getIngestChunkSettingsError({ chunkSize: 1, chunkOverlap: 0 }),
    ).toBeNull();
  });
});
