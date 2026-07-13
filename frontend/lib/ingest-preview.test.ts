import {
  chunkPageToDoclingRef,
  inferChunkPageNumbering,
  isIngestPreviewEnabled,
} from "@/lib/ingest-preview";

describe("ingest-preview", () => {
  it("is enabled only in OSS run mode", () => {
    expect(isIngestPreviewEnabled("oss")).toBe(true);
    expect(isIngestPreviewEnabled("saas")).toBe(false);
    expect(isIngestPreviewEnabled("on_prem")).toBe(false);
    expect(isIngestPreviewEnabled(null)).toBe(false);
  });

  it("detects chunk page numbering", () => {
    expect(inferChunkPageNumbering([{ page: 0 }, { page: 1 }])).toBe(
      "zero-based",
    );
    expect(inferChunkPageNumbering([{ page: 1 }, { page: 2 }])).toBe(
      "one-based",
    );
  });

  it("maps chunk pages to Docling refs", () => {
    expect(chunkPageToDoclingRef(0, "zero-based")).toBe("#/pages/1");
    expect(chunkPageToDoclingRef(2, "zero-based")).toBe("#/pages/3");
    expect(chunkPageToDoclingRef(1, "one-based")).toBe("#/pages/1");
  });
});
