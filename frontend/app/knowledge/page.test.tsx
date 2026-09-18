/**
 * KnowledgePage — tests for the chunks-navigation URL helper.
 *
 * The filename→chunks click handler lives inside an ag-Grid cellRenderer, which
 * jsdom cannot exercise (no layout engine; cell renderers never mount). Geometry-
 * and grid-dependent behaviour belongs in Playwright.
 *
 * What we CAN test in Vitest is the pure URL-building logic. It is extracted
 * into buildChunksUrl() in page.tsx so this test imports and calls the real
 * production function rather than re-implementing it inline.
 */
import { describe, expect, it } from "vitest";
import { buildChunksUrl } from "./page";

describe("buildChunksUrl", () => {
  it("includes ?q= when effectiveSearchText is a non-wildcard term", () => {
    const url = buildChunksUrl("report.pdf", "quarterly revenue");
    expect(url).toBe(
      "/knowledge/chunks?filename=report.pdf&q=quarterly+revenue",
    );
  });

  it("omits ?q= when effectiveSearchText is the wildcard '*'", () => {
    const url = buildChunksUrl("report.pdf", "*");
    expect(url).toBe("/knowledge/chunks?filename=report.pdf");
  });

  it("omits ?q= when effectiveSearchText is an empty string", () => {
    const url = buildChunksUrl("report.pdf", "");
    expect(url).toBe("/knowledge/chunks?filename=report.pdf");
  });

  it("omits ?q= when effectiveSearchText is whitespace only", () => {
    const url = buildChunksUrl("report.pdf", "   ");
    expect(url).toBe("/knowledge/chunks?filename=report.pdf");
  });

  it("URL-encodes special characters in filename and query", () => {
    const url = buildChunksUrl("my doc & notes.pdf", "cost/benefit");
    expect(url).toContain("filename=my+doc+%26+notes.pdf");
    expect(url).toContain("q=cost%2Fbenefit");
  });
});
