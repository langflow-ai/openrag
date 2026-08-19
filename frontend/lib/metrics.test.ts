import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { normalizePath, normalizeRoute } from "./metrics";

describe("normalizeRoute", () => {
  it("collapses per-chunk static asset paths", () => {
    assert.equal(
      normalizeRoute("/_next/static/chunks/abc123.js"),
      "/_next/static/*",
    );
    assert.equal(
      normalizeRoute("/_next/static/css/9f2c1d.css"),
      "/_next/static/*",
    );
  });

  it("collapses per-build data paths", () => {
    assert.equal(
      normalizeRoute("/_next/data/buildid/page.json"),
      "/_next/data/*",
    );
  });

  it("leaves other /_next paths alone", () => {
    assert.equal(normalizeRoute("/_next/image"), "/_next/image");
  });

  it("delegates to normalizePath for non-static paths", () => {
    assert.equal(
      normalizeRoute("/api/providers/abc-123/models"),
      normalizePath("/api/providers/abc-123/models"),
    );
    assert.equal(
      normalizeRoute("/chat/550e8400-e29b-41d4-a716-446655440000"),
      "/chat/:id",
    );
    assert.equal(normalizeRoute("/favicon.ico"), "/favicon.ico");
    assert.equal(normalizeRoute("/"), "/");
  });
});
