/**
 * Unit tests for pure helpers extracted from knowledge/page.tsx.
 *
 * Covers the lines added in #2388:
 *   getStatusSortRank — "skipped" (rank 4) and "hidden" (rank 7)
 *   getSkippedWarningText — returns the provided warning or the default fallback
 *
 * These functions are pure and have no React / ag-grid / browser dependencies,
 * so they can be tested without rendering the page at all.
 */
import { describe, expect, it } from "vitest";
import { getSkippedWarningText, getStatusSortRank } from "./page";

describe("getStatusSortRank", () => {
  it("ranks skipped above cancelled", () => {
    expect(getStatusSortRank("skipped")).toBe(4);
    expect(getStatusSortRank("cancelled")).toBe(5);
    expect(getStatusSortRank("skipped")).toBeLessThan(
      getStatusSortRank("cancelled"),
    );
  });

  it("returns 7 for hidden", () => {
    expect(getStatusSortRank("hidden")).toBe(7);
  });

  it("returns 0 for active and for unknown values", () => {
    expect(getStatusSortRank("active")).toBe(0);
    expect(getStatusSortRank(undefined)).toBe(0);
  });
});

describe("getSkippedWarningText", () => {
  it("returns the provided warning when present", () => {
    const msg =
      "Identical content already exists in the knowledge base under a different filename.";
    expect(getSkippedWarningText(msg)).toBe(msg);
  });

  it("returns the default fallback when warning is undefined", () => {
    const result = getSkippedWarningText(undefined);
    expect(result).toBe(
      "Duplicate content — already exists in the knowledge base.",
    );
  });
});
