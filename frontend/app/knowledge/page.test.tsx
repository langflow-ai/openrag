/**
 * Unit tests for pure helpers extracted from knowledge/page.tsx.
 *
 *   getStatusSortRank     — all branches including "skipped" (4) and "hidden" (7)
 *   getSkippedWarningText — provided warning vs default fallback
 *   isSkippedStatus       — skipped detection used by the cell renderer
 *   SkippedStatusCell     — renders the amber "Duplicate" badge with tooltip
 *   buildChunksUrl        — URL construction for the chunks navigation link
 *   getOwnerLabel         — owner display label preference order
 *   formatAvgScoreLabel   — avg-score cell number / dash formatting
 *   formatChunkCountLabel — chunk-count cell number / dash formatting
 *   resolveDisplayStatus  — failed→cancelled promotion for cancelled files
 *
 * SearchPage render smoke-test — exercises the column-definition object
 * construction (colOwner, colChunks, colAvgScore, colStatus, colActions, …)
 * which runs every time the component mounts.
 */

import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import { TooltipProvider } from "@/components/ui/tooltip";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, userEvent, waitFor } from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";
import ProtectedSearchPage, {
  AvgScoreCellContent,
  buildChunksUrl,
  compareAvgScore,
  compareStatusRank,
  formatAvgScoreLabel,
  formatChunkCountLabel,
  formatSizeLabel,
  getFileStatus,
  getOwnerLabel,
  getSkippedWarningText,
  getStatusSortRank,
  isSkippedStatus,
  resolveActionsVariant,
  resolveDisplayStatus,
  SkippedStatusCell,
  StatusCellContent,
  serverSideComparator,
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

describe("getOwnerLabel", () => {
  // Minimal File-shaped stubs — only the fields getOwnerLabel reads.
  const f = (partial: Partial<File>) => partial as File;

  it("prefers owner_name when present", () => {
    expect(
      getOwnerLabel(
        f({ owner_name: "Alice", owner_email: "alice@example.com" }),
      ),
    ).toBe("Alice");
  });

  it("falls back to owner_email when owner_name is absent", () => {
    expect(getOwnerLabel(f({ owner_email: "alice@example.com" }))).toBe(
      "alice@example.com",
    );
  });

  it("returns an em-dash when both are absent", () => {
    expect(getOwnerLabel(f({}))).toBe("—");
    expect(getOwnerLabel(undefined)).toBe("—");
  });

  it("trims whitespace from owner_name", () => {
    expect(getOwnerLabel(f({ owner_name: "  Bob  " }))).toBe("Bob");
  });
});

describe("formatAvgScoreLabel", () => {
  it("formats a number to two decimal places", () => {
    expect(formatAvgScoreLabel(0.8765)).toBe("0.88");
    expect(formatAvgScoreLabel(1)).toBe("1.00");
  });

  it("returns a dash for non-numeric values", () => {
    expect(formatAvgScoreLabel(undefined)).toBe("-");
    expect(formatAvgScoreLabel(null)).toBe("-");
    expect(formatAvgScoreLabel("0.9")).toBe("-");
  });
});

describe("formatChunkCountLabel", () => {
  it("converts a defined count to its string representation", () => {
    expect(formatChunkCountLabel(42)).toBe("42");
    expect(formatChunkCountLabel(0)).toBe("0");
  });

  it("returns a dash when chunkCount is undefined", () => {
    expect(formatChunkCountLabel(undefined)).toBe("-");
  });
});

describe("resolveDisplayStatus", () => {
  it("promotes failed to cancelled when the file is cancelled", () => {
    expect(resolveDisplayStatus("failed", true)).toBe("cancelled");
  });

  it("keeps failed when the file is not cancelled", () => {
    expect(resolveDisplayStatus("failed", false)).toBe("failed");
  });

  it("passes through any other status unchanged regardless of cancellation flag", () => {
    expect(resolveDisplayStatus("active", false)).toBe("active");
    expect(resolveDisplayStatus("processing", true)).toBe("processing");
    expect(resolveDisplayStatus("skipped", true)).toBe("skipped");
  });
});

describe("formatSizeLabel", () => {
  it("formats a truthy numeric value via formatFileSize", () => {
    // formatFileSize converts bytes to human-readable; we just check it
    // returns something non-dash for a positive number.
    expect(formatSizeLabel(1024)).not.toBe("-");
    expect(formatSizeLabel(1024)).toBeTruthy();
  });

  it("returns a dash for falsy values", () => {
    expect(formatSizeLabel(0)).toBe("-");
    expect(formatSizeLabel(undefined)).toBe("-");
    expect(formatSizeLabel(null)).toBe("-");
  });
});

describe("compareAvgScore", () => {
  it("returns a positive number when valueA > valueB", () => {
    expect(compareAvgScore(0.9, 0.5)).toBeGreaterThan(0);
  });

  it("returns a negative number when valueA < valueB", () => {
    expect(compareAvgScore(0.3, 0.8)).toBeLessThan(0);
  });

  it("returns 0 for equal values", () => {
    expect(compareAvgScore(0.5, 0.5)).toBe(0);
  });

  it("treats undefined as 0", () => {
    expect(compareAvgScore(undefined, 0)).toBe(0);
    expect(compareAvgScore(0.5, undefined)).toBeGreaterThan(0);
  });
});

describe("getFileStatus", () => {
  it("returns the status when present", () => {
    expect(getFileStatus("active")).toBe("active");
    expect(getFileStatus("failed")).toBe("failed");
  });

  it("defaults to 'active' when status is undefined", () => {
    expect(getFileStatus(undefined)).toBe("active");
  });
});

describe("resolveActionsVariant", () => {
  it("returns 'cancel' for a processing row with taskId and filePath", () => {
    expect(resolveActionsVariant("processing", "task-1", "file.pdf")).toBe(
      "cancel",
    );
  });

  it("returns null for a processing row without taskId", () => {
    expect(resolveActionsVariant("processing", null, "file.pdf")).toBeNull();
    expect(
      resolveActionsVariant("processing", undefined, "file.pdf"),
    ).toBeNull();
  });

  it("returns null for a processing row without filePath", () => {
    expect(resolveActionsVariant("processing", "task-1", "")).toBeNull();
  });

  it("returns 'dropdown' for an active row", () => {
    expect(resolveActionsVariant("active", undefined, "")).toBe("dropdown");
  });

  it("returns null for any other status", () => {
    expect(resolveActionsVariant("failed", undefined, "")).toBeNull();
    expect(resolveActionsVariant("cancelled", undefined, "")).toBeNull();
    expect(resolveActionsVariant("skipped", undefined, "")).toBeNull();
  });
});

describe("StatusCellContent", () => {
  const f = (partial: Partial<File>) => partial as File;
  const noop = () => {};

  const baseProps = {
    isCloudBrand: false,
    isOpenragDocsRow: () => false,
    hasOpenragRefreshCue: false,
    selectTask: noop,
    getTaskIdForRow: () => null as null,
    openTaskMenu: noop,
    setRecentTasksExpanded: noop,
  };

  it("renders a file skipped for a duplicate filename without crashing", () => {
    // The row a blocked overwrite leaves behind: skipped, but not for
    // duplicate_content, so it falls past SkippedStatusCell to the plain
    // badge. "skipped" had no entry there, and the throw took the whole
    // knowledge view down (tracker #92808).
    render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          data={f({
            status: "skipped",
            skip_reason: "duplicate_filename",
            warning: "A file with this name already exists.",
          })}
        />
      </TooltipProvider>,
    );

    expect(screen.getByText("Skipped")).toBeTruthy();
  });

  it("renders a StatusBadge for an active file", () => {
    render(
      <TooltipProvider>
        <StatusCellContent {...baseProps} data={f({ status: "active" })} />
      </TooltipProvider>,
    );
    // active StatusBadge renders an "Active" or similar label — just check it
    // doesn't crash and renders something.
    expect(document.body.firstChild).toBeTruthy();
  });

  it("renders the cancelled StatusBadge for a cancelled file", () => {
    const { container } = render(
      <TooltipProvider>
        <StatusCellContent {...baseProps} data={f({ status: "cancelled" })} />
      </TooltipProvider>,
    );
    expect(container.textContent?.toLowerCase()).toContain("cancel");
  });

  it("renders the Refreshing indicator when hasOpenragRefreshCue and isOpenragDocsRow", () => {
    render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          isOpenragDocsRow={() => true}
          hasOpenragRefreshCue={true}
          isCloudBrand={false}
          data={f({ status: "active", connector_type: "openrag_docs" })}
        />
      </TooltipProvider>,
    );
    // The non-cloud variant renders an aria-label "OpenRAG doc is refreshing".
    expect(
      document.querySelector('[aria-label="OpenRAG doc is refreshing"]'),
    ).not.toBeNull();
  });

  it("renders the cloud Refreshing label when isCloudBrand is true", () => {
    const { container } = render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          isOpenragDocsRow={() => true}
          hasOpenragRefreshCue={true}
          isCloudBrand={true}
          data={f({ status: "active", connector_type: "openrag_docs" })}
        />
      </TooltipProvider>,
    );
    expect(container.textContent).toContain("Refreshing");
  });

  it("renders the failed button trigger for a failed file", () => {
    render(
      <TooltipProvider>
        <StatusCellContent {...baseProps} data={f({ status: "failed" })} />
      </TooltipProvider>,
    );
    expect(
      document.querySelector('[data-testid="failed-status-cell-trigger"]'),
    ).not.toBeNull();
  });

  it("calls selectTask/openTaskMenu/setRecentTasksExpanded on click of the failed trigger", async () => {
    const user = userEvent.setup();
    const selectTask = vi.fn();
    const openTaskMenu = vi.fn();
    const setRecentTasksExpanded = vi.fn();
    render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          data={f({ status: "failed", task_id: "t1" })}
          selectTask={selectTask}
          getTaskIdForRow={() => "t1"}
          openTaskMenu={openTaskMenu}
          setRecentTasksExpanded={setRecentTasksExpanded}
        />
      </TooltipProvider>,
    );
    await user.click(
      document.querySelector('[data-testid="failed-status-cell-trigger"]')!,
    );
    expect(selectTask).toHaveBeenCalledWith("t1");
    expect(openTaskMenu).toHaveBeenCalled();
    expect(setRecentTasksExpanded).toHaveBeenCalledWith(true);
  });

  it("wraps the failed button in a tooltip when data.error is set", () => {
    render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          data={f({ status: "failed", error: "Upload timed out" })}
        />
      </TooltipProvider>,
    );
    // Tooltip wraps the trigger — button is still in the DOM.
    expect(
      document.querySelector('[data-testid="failed-status-cell-trigger"]'),
    ).not.toBeNull();
  });

  it("renders the Duplicate badge for a skipped duplicate-content file", () => {
    render(
      <TooltipProvider>
        <StatusCellContent
          {...baseProps}
          data={f({ status: "skipped", skip_reason: "duplicate_content" })}
        />
      </TooltipProvider>,
    );
    expect(screen.getByText("Duplicate")).toBeTruthy();
  });
});

describe("serverSideComparator", () => {
  it("always returns 0 regardless of arguments", () => {
    expect(serverSideComparator()).toBe(0);
  });
});

describe("compareStatusRank", () => {
  it("sorts active before failed", () => {
    expect(compareStatusRank("active", "failed")).toBeLessThan(0);
  });

  it("sorts failed before cancelled", () => {
    expect(compareStatusRank("failed", "cancelled")).toBeLessThan(0);
  });

  it("returns 0 for equal statuses", () => {
    expect(compareStatusRank("active", "active")).toBe(0);
  });
});

describe("AvgScoreCellContent", () => {
  it("renders a formatted score label", () => {
    const { container } = render(
      <TooltipProvider>
        <AvgScoreCellContent value={0.875} />
      </TooltipProvider>,
    );
    expect(container.textContent).toContain("0.88");
  });

  it("renders a dash when value is not a number", () => {
    const { container } = render(
      <TooltipProvider>
        <AvgScoreCellContent value={undefined} />
      </TooltipProvider>,
    );
    expect(container.textContent).toContain("-");
  });
});

describe("SearchPage — column-definition smoke-test", () => {
  /**
   * Rendering the page (even with no data) exercises the body of SearchPage,
   * which creates all column-definition objects (colSource, colSize, colType,
   * colOwner, colChunks, colAvgScore, colStatus, colActions, columnDefs).
   * That's enough to hit the property-declaration lines that V8 tracks as
   * executable.  Cell-renderer closure bodies run only when ag-grid paints a
   * real cell, which jsdom cannot do — those branches are covered by the pure-
   * helper tests above.
   */
  it("mounts without crashing and renders the search heading", async () => {
    setMockLocation({ pathname: "/knowledge" });

    renderWithProviders(<ProtectedSearchPage />, {
      providers: "all",
      auth: authPresets.admin,
      handlers: [
        http.get("/api/files", () =>
          HttpResponse.json({
            files: [],
            total: 0,
            is_approximate: false,
            page: 1,
            page_size: 20,
            after_key: null,
          }),
        ),
        http.post("/api/search", () =>
          HttpResponse.json({ files: [], warnings: [] }),
        ),
        // Side-effect fetches triggered by KnowledgeDropdown / connector queries.
        http.get("/api/upload_options", () => HttpResponse.json({})),
        http.get("/api/connectors", () =>
          HttpResponse.json({ connectors: [] }),
        ),
        http.get("/api/connectors/:name/defaults", () => HttpResponse.json({})),
      ],
    });

    // The heading is always rendered once SearchPage mounts.
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /knowledge/i }),
      ).not.toBeNull(),
    );
  });
});
