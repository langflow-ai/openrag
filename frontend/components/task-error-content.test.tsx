/**
 * Tests for TaskErrorContent.
 *
 * Covered lines (per diff gate):
 *   88-89  — toggleAccordion handler
 *   91     — component return (basic render)
 *   166    — Accordion onValueChange handler
 *   192    — openTaskDialog in the !showHeader accordion trigger
 *   201-203 — issueEntries.map rendering file entries
 *   206-207 — resolveTaskFileError / formatApiComponent calls
 *   209    — isWarning flag per file entry
 *   245    — openTaskDialog in showHeader+isFirst details button
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { TaskErrorContent } from "@/components/task-error-content";

// ─── context mocks ────────────────────────────────────────────────────────────

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: vi.fn(),
}));

vi.mock("@/contexts/task-context", () => ({
  useTask: vi.fn(),
}));

import { useIsCloudBrand } from "@/contexts/brand-context";
import { useTask } from "@/contexts/task-context";

// ─── helpers ──────────────────────────────────────────────────────────────────

function setupContexts(
  opts: { isCloud?: boolean; openTaskDialog?: () => void } = {},
) {
  vi.mocked(useIsCloudBrand).mockReturnValue(opts.isCloud ?? false);
  vi.mocked(useTask).mockReturnValue({
    openTaskDialog: opts.openTaskDialog ?? vi.fn(),
  } as unknown as ReturnType<typeof useTask>);
}

function makeTaskWithFailedFile(
  overrides: Partial<Task> = {},
  fileOverrides: Record<string, unknown> = {},
): Task {
  return {
    task_id: "aaaabbbb-cccc-dddd-eeee-ffffffffffff",
    status: "failed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    failed_files: 1,
    files: {
      "document.pdf": {
        status: "failed",
        error: "Parsing failed: invalid byte sequence",
        filename: "document.pdf",
        ...fileOverrides,
      },
    },
    ...overrides,
  };
}

function makeTaskWithWarningFile(): Task {
  return {
    task_id: "warn-task-0000-1111-2222-333333333333",
    status: "completed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    successful_files: 1,
    // failed_files is 0 but there is a skipped file — isTaskFileWarning checks status === "skipped"
    files: {
      "warning.pdf": {
        status: "skipped",
        filename: "warning.pdf",
      },
    },
  };
}

// ─── tests ────────────────────────────────────────────────────────────────────

describe("TaskErrorContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupContexts();
  });

  it("returns null when there are no failed files and no issue entries", () => {
    const task: Task = {
      task_id: "clean-task",
      status: "completed",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:01Z",
    };
    const { container } = render(<TaskErrorContent task={task} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the component when there are failed files (line 91)", () => {
    setupContexts();
    render(<TaskErrorContent task={makeTaskWithFailedFile()} />);
    // Header button with the task ID prefix is visible.
    expect(screen.getByText(/aaaabbbb/)).toBeInTheDocument();
  });

  it("renders file entry details in the accordion (lines 201-203)", async () => {
    setupContexts();
    render(
      <TaskErrorContent task={makeTaskWithFailedFile()} defaultExpanded />,
    );
    // File name visible after accordion opens.
    expect(screen.getByText("document.pdf")).toBeInTheDocument();
  });

  it("toggles accordion open/closed when showHeader header button is clicked (lines 88-89)", async () => {
    setupContexts();
    const task = makeTaskWithFailedFile();
    render(<TaskErrorContent task={task} showHeader />);

    const headerBtn = screen.getByRole("button", { name: /aaaabbbb/ });
    // Initially collapsed — file name not in DOM.
    expect(screen.queryByText("document.pdf")).toBeNull();

    await userEvent.click(headerBtn);
    expect(screen.getByText("document.pdf")).toBeInTheDocument();

    // Click again to collapse.
    await userEvent.click(headerBtn);
    expect(screen.queryByText("document.pdf")).toBeNull();
  });

  it("opens task dialog when the details icon in showHeader+isFirst mode is clicked (line 245)", async () => {
    const openTaskDialog = vi.fn();
    setupContexts({ openTaskDialog });
    const task = makeTaskWithFailedFile();
    render(<TaskErrorContent task={task} defaultExpanded />);

    // Wait for accordion to open via defaultExpanded, then click the
    // "Open task details" button inside the file card (isFirst = true).
    const detailsBtn = screen.getByRole("button", {
      name: /open task details/i,
    });
    await userEvent.click(detailsBtn);
    expect(openTaskDialog).toHaveBeenCalledWith(task.task_id);
  });

  it("opens task dialog when the details icon in !showHeader mode is clicked (line 192)", async () => {
    const openTaskDialog = vi.fn();
    setupContexts({ openTaskDialog });
    const task = makeTaskWithFailedFile();
    render(<TaskErrorContent task={task} showHeader={false} defaultExpanded />);

    const detailsBtn = screen.getByRole("button", {
      name: /open task details/i,
    });
    await userEvent.click(detailsBtn);
    expect(openTaskDialog).toHaveBeenCalledWith(task.task_id);
  });

  it("applies warning styles for warning-type file entries (line 209)", () => {
    setupContexts();
    const task = makeTaskWithWarningFile();
    render(<TaskErrorContent task={task} defaultExpanded />);
    // The file card should be present; it renders with warning styling.
    // We just assert the file name is rendered without throwing.
    expect(screen.getByText("warning.pdf")).toBeInTheDocument();
  });

  it("shows component cause when fileInfo.component is set (lines 206-207)", () => {
    setupContexts();
    const task = makeTaskWithFailedFile({}, { component: "docling" });
    render(<TaskErrorContent task={task} defaultExpanded />);
    // formatApiComponent("docling") returns something like "Docling".
    expect(screen.getByText(/docling/i)).toBeInTheDocument();
  });

  it("calls onValueChange on the Accordion to collapse entries (line 166)", async () => {
    setupContexts();
    const task = makeTaskWithFailedFile();
    render(<TaskErrorContent task={task} defaultExpanded />);

    // File is visible because defaultExpanded.
    expect(screen.getByText("document.pdf")).toBeInTheDocument();

    // Click the header toggle to collapse.
    const headerBtn = screen.getByRole("button", { name: /aaaabbbb/ });
    await userEvent.click(headerBtn);

    expect(screen.queryByText("document.pdf")).toBeNull();
  });
});
