import assert from "node:assert/strict";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getChunkSettingsError,
  getIngestChunkSettingsError,
  validateIngestSettingsOrToast,
} from "./types";

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

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

describe("getChunkSettingsError", () => {
  it("returns null for valid settings", () => {
    expect(
      getChunkSettingsError({ chunkSize: 1024, chunkOverlap: 50 }),
    ).toBeNull();
  });

  it("returns null when overlap is 0", () => {
    expect(
      getChunkSettingsError({ chunkSize: 1024, chunkOverlap: 0 }),
    ).toBeNull();
  });

  it("returns null when overlap is exactly chunkSize - 1 (boundary)", () => {
    expect(
      getChunkSettingsError({ chunkSize: 1024, chunkOverlap: 1023 }),
    ).toBeNull();
  });

  it("returns chunk size error when chunkSize is 0", () => {
    expect(getChunkSettingsError({ chunkSize: 0, chunkOverlap: 0 })).toBe(
      "Chunk size must be at least 1",
    );
  });

  it("returns chunk size error when chunkSize is negative", () => {
    expect(getChunkSettingsError({ chunkSize: -5, chunkOverlap: 0 })).toBe(
      "Chunk size must be at least 1",
    );
  });

  it("returns overlap error when chunkOverlap equals chunkSize", () => {
    expect(getChunkSettingsError({ chunkSize: 100, chunkOverlap: 100 })).toBe(
      "Chunk overlap must be less than chunk size",
    );
  });

  it("returns overlap error when chunkOverlap exceeds chunkSize", () => {
    expect(getChunkSettingsError({ chunkSize: 100, chunkOverlap: 200 })).toBe(
      "Chunk overlap must be less than chunk size",
    );
  });

  it("chunk size error takes priority when both would fire (size=0, overlap=999)", () => {
    expect(getChunkSettingsError({ chunkSize: 0, chunkOverlap: 999 })).toBe(
      "Chunk size must be at least 1",
    );
  });

  it("returns null for minimum valid config (chunkSize: 1, chunkOverlap: 0)", () => {
    expect(getChunkSettingsError({ chunkSize: 1, chunkOverlap: 0 })).toBeNull();
  });
});

describe("validateIngestSettingsOrToast", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
  });

  it("passes when no settings were provided", () => {
    expect(validateIngestSettingsOrToast(undefined)).toBe(true);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("passes valid settings without a toast", () => {
    expect(validateIngestSettingsOrToast(validSettings)).toBe(true);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("blocks invalid settings and explains why in a toast", () => {
    expect(
      validateIngestSettingsOrToast({
        ...validSettings,
        chunkSize: 100,
        chunkOverlap: 100,
      }),
    ).toBe(false);
    expect(toast.error).toHaveBeenCalledWith("Could not start ingest", {
      description: "Chunk overlap must be less than chunk size",
    });
  });

  it("blocks a missing embedding model", () => {
    expect(
      validateIngestSettingsOrToast({ ...validSettings, embeddingModel: "" }),
    ).toBe(false);
    expect(toast.error).toHaveBeenCalledWith("Could not start ingest", {
      description:
        "Select an embedding model in Settings before ingesting files",
    });
  });
});
