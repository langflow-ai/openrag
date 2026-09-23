/**
 * Unit tests for pure helpers extracted from knowledge/page.tsx.
 *
 * Covers the lines added / changed in #2388:
 *   getStatusSortRank  — all branches including "skipped" (4) and "hidden" (7)
 *   getSkippedWarningText — provided warning vs default fallback
 *   isSkippedStatus       — skipped detection used by the cell renderer
 *   SkippedStatusCell     — renders the amber "Duplicate" badge with tooltip
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  buildChunksUrl,
  getSkippedWarningText,
  getStatusSortRank,
  isSkippedStatus,
  SkippedStatusCell,
} from "./page";

describe("getStatusSortRank", () => {
  it("ranks every status in the correct order", () => {
    expect(getStatusSortRank("active")).toBe(0);
    expect(getStatusSortRank("processing")).toBe(1);
    expect(getStatusSortRank("sync")).toBe(2);
    expect(getStatusSortRank("failed")).toBe(3);
    expect(getStatusSortRank("skipped")).toBe(4);
    expect(getStatusSortRank("cancelled")).toBe(5);
    expect(getStatusSortRank("unavailable")).toBe(6);
    expect(getStatusSortRank("hidden")).toBe(7);
  });

  it("returns 0 for undefined and unknown values", () => {
    expect(getStatusSortRank(undefined)).toBe(0);
  });

  it("ranks skipped below failed but above cancelled", () => {
    expect(getStatusSortRank("skipped")).toBeGreaterThan(
      getStatusSortRank("failed"),
    );
    expect(getStatusSortRank("skipped")).toBeLessThan(
      getStatusSortRank("cancelled"),
    );
  });
});

describe("getSkippedWarningText", () => {
  it("returns the provided warning when present", () => {
    const msg =
      "Identical content already exists in the knowledge base under a different filename.";
    expect(getSkippedWarningText(msg)).toBe(msg);
  });

  it("returns the default fallback when warning is undefined", () => {
    expect(getSkippedWarningText(undefined)).toBe(
      "Duplicate content — already exists in the knowledge base.",
    );
  });
});

describe("isSkippedStatus", () => {
  it("returns true only for skipped + duplicate_content reason", () => {
    expect(isSkippedStatus("skipped", "duplicate_content")).toBe(true);
  });

  it("returns false when status is skipped but reason is not duplicate_content", () => {
    expect(isSkippedStatus("skipped", "deleted_at_source")).toBe(false);
    expect(isSkippedStatus("skipped", undefined)).toBe(false);
  });

  it("returns false for any other status", () => {
    expect(isSkippedStatus("active", "duplicate_content")).toBe(false);
    expect(isSkippedStatus("failed")).toBe(false);
    expect(isSkippedStatus(undefined)).toBe(false);
  });
});

describe("SkippedStatusCell", () => {
  it("renders the visible Duplicate label for both warning variants", () => {
    // Radix TooltipContent is not in the DOM until hover — assert only the
    // always-visible trigger span. Warning text is covered by getSkippedWarningText tests.
    const { rerender } = render(
      <TooltipProvider>
        <SkippedStatusCell warning="Identical content already exists." />
      </TooltipProvider>,
    );
    expect(screen.getByText("Duplicate")).toBeTruthy();

    rerender(
      <TooltipProvider>
        <SkippedStatusCell />
      </TooltipProvider>,
    );
    expect(screen.getByText("Duplicate")).toBeTruthy();
  });
});

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
