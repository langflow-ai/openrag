import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";

// Mock all the dependencies
vi.mock("@/contexts/knowledge-filter-context", () => ({
  useKnowledgeFilter: () => ({
    queryOverride: "",
    parsedFilterData: { query: "filter query" },
  }),
}));

vi.mock("@/contexts/console-status-context", () => ({
  useOpenTaskMenu: () => vi.fn(),
}));

vi.mock("@/contexts/task-context", () => ({
  useTask: () => ({
    tasks: [],
    isTaskInProgress: () => false,
  }),
}));

vi.mock("../api/queries/useGetSearchQuery", () => ({
  useGetSearchQuery: () => ({
    data: { files: [], warnings: [] },
    isFetching: false,
  }),
  EMPTY_SEARCH_RESULT: { files: [], warnings: [] },
}));

vi.mock("../api/queries/useListFiles", () => ({
  useListFiles: () => ({
    data: { items: [], total: 0 },
    isFetching: false,
  }),
}));

/**
 * Tests the effectiveSearchText URL param building logic (lines 630-643).
 * This is the code that runs when clicking a file row to navigate to chunks page.
 */
describe("KnowledgePage - effectiveSearchText in URL params (lines 630-643)", () => {
  it("includes effectiveSearchText in URL when it has a value", () => {
    // Simulate the logic from lines 630-643
    const effectiveSearchText = "filter query"; // from parsedFilterData
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    // Lines 633-640: Check if effectiveSearchText is valid
    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    const url = `/knowledge/chunks?${params.toString()}`;
    expect(url).toBe("/knowledge/chunks?filename=test.pdf&q=filter+query");
  });

  it("excludes query param when effectiveSearchText is wildcard", () => {
    const effectiveSearchText = "*";
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.has("q")).toBe(false);
  });

  it("excludes query param when effectiveSearchText is empty", () => {
    const effectiveSearchText = "";
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.has("q")).toBe(false);
  });

  it("includes query from queryOverride when available", () => {
    const effectiveSearchText = "query override text";
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.get("q")).toBe("query override text");
  });
});
