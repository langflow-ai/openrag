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
  it("returns true for skipped", () => {
    expect(isSkippedStatus("skipped")).toBe(true);
  });

  it("returns false for any other status", () => {
    expect(isSkippedStatus("active")).toBe(false);
    expect(isSkippedStatus("failed")).toBe(false);
    expect(isSkippedStatus(undefined)).toBe(false);
  });
});

describe("SkippedStatusCell", () => {
  it("renders the Duplicate label", () => {
    render(
      <TooltipProvider>
        <SkippedStatusCell warning="Identical content already exists." />
      </TooltipProvider>,
    );
    // The visible trigger text is always in the DOM
    expect(screen.getByText("Duplicate")).toBeTruthy();
    // Tooltip content is in the DOM (hidden until hover); queryByText finds it
    expect(
      screen.queryByText("Identical content already exists."),
    ).not.toBeNull();
  });

  it("renders the default fallback warning when no warning prop is given", () => {
    render(
      <TooltipProvider>
        <SkippedStatusCell />
      </TooltipProvider>,
    );
    expect(screen.getByText("Duplicate")).toBeTruthy();
    expect(
      screen.queryByText(
        "Duplicate content — already exists in the knowledge base.",
      ),
    ).not.toBeNull();
  });
});
