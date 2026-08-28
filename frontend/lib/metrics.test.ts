import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { normalizePath, normalizeRoute } from "./metrics";

describe("normalizeRoute", () => {
  it("collapses all /_next/* paths", () => {
    assert.equal(normalizeRoute("/_next/static/chunks/abc123.js"), "/_next/*");
    assert.equal(normalizeRoute("/_next/data/buildid/page.json"), "/_next/*");
    assert.equal(normalizeRoute("/_next/image"), "/_next/*");
  });

  it("buckets unknown prefixes as unmatched", () => {
    assert.equal(normalizeRoute("/favicon.ico"), "unmatched");
    assert.equal(normalizeRoute("/wp-login.php"), "unmatched");
    assert.equal(normalizeRoute("/.env"), "unmatched");
  });

  it("passes root through", () => {
    assert.equal(normalizeRoute("/"), "/");
  });

  it("delegates to normalizePath for known prefixes", () => {
    assert.equal(
      normalizeRoute("/api/providers/abc-123/models"),
      normalizePath("/api/providers/abc-123/models"),
    );
    assert.equal(
      normalizeRoute("/chat/550e8400-e29b-41d4-a716-446655440000"),
      "/chat/:id",
    );
    assert.equal(normalizeRoute("/settings/general"), "/settings/general");
    assert.equal(normalizeRoute("/health"), "/health");
  });
});
