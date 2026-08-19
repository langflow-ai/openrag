import assert from "node:assert/strict";
import { describe, it } from "node:test";

const sourceUrlModule = "./source-url.ts";
const { getPreviewSourceUrl, getSourcePreviewKind } = await import(
  sourceUrlModule
);

describe("getPreviewSourceUrl", () => {
  it("targets a PDF reference page for managed sources", () => {
    assert.equal(
      getPreviewSourceUrl(
        "/api/source-files/abcdefghijklmnop.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        7,
      ),
      "/api/source-files/abcdefghijklmnop.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?preview=true#page=7",
    );
  });

  it("preserves normal preview behavior without a valid page", () => {
    assert.equal(
      getPreviewSourceUrl("https://example.com/report.pdf", 0),
      "https://example.com/report.pdf",
    );
  });
});

describe("getSourcePreviewKind", () => {
  it("recognizes extensionless sources by MIME type", () => {
    assert.equal(getSourcePreviewKind("source", "application/pdf"), "document");
  });
});
