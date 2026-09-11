import { describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { renderWithProviders, screen } from "@/test-utils/render";
import { TaskErrorContent } from "./task-error-content";

/**
 * Tests for the cancellation-specific branches added to TaskErrorContent:
 *   - isCancelledOnly derived from isFileCancelled
 *   - "Cancelled" status label
 *   - "cancelled" count in the summary line
 *   - early-return when all counts are zero
 *
 * TaskErrorContent depends on useTask (for openTaskDialog) and useIsCloudBrand.
 * Both are mocked at the module level — the context providers are not needed
 * because we are testing component logic, not the context wiring.
 */

vi.mock("@/contexts/task-context", () => ({
  useTask: () => ({ openTaskDialog: vi.fn() }),
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: () => false,
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    task_id: "t1",
    status: "completed",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:05:00Z",
    ...overrides,
  };
}

describe("TaskErrorContent — cancellation display", () => {
  it("renders 'Cancelled' status pill when all failures are user cancellations", () => {
    const task = makeTask({
      status: "cancelled",
      failed_files: 1,
      files: {
        "file.pdf": {
          status: "failed",
          error: "Task cancelled by user",
        },
      },
    });

    renderWithProviders(<TaskErrorContent task={task} />);

    expect(screen.getByText("Cancelled")).toBeInTheDocument();
  });

  it("includes the cancelled count in the summary line", () => {
    const task = makeTask({
      status: "cancelled",
      failed_files: 2,
      files: {
        "a.pdf": { status: "failed", error: "Task cancelled by user" },
        "b.pdf": { status: "failed", error: "Task cancelled by user" },
      },
    });

    renderWithProviders(<TaskErrorContent task={task} />);

    expect(screen.getByText(/2 cancelled/)).toBeInTheDocument();
  });

  it("returns null (renders nothing) when there are no failures, cancellations, or warnings", () => {
    const task = makeTask({
      status: "completed",
      successful_files: 3,
      files: {
        "a.pdf": { status: "completed" },
        "b.pdf": { status: "completed" },
        "c.pdf": { status: "completed" },
      },
    });

    const { container } = renderWithProviders(<TaskErrorContent task={task} />);

    expect(container.firstChild).toBeNull();
  });

  it("shows 'Failed' label when there are real (non-cancellation) failures", () => {
    const task = makeTask({
      status: "failed",
      failed_files: 1,
      files: {
        "file.pdf": { status: "failed", error: "Parsing error" },
      },
    });

    renderWithProviders(<TaskErrorContent task={task} />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows both failed and cancelled counts when a task has mixed failures", () => {
    const task = makeTask({
      status: "completed",
      failed_files: 2,
      files: {
        "cancelled.pdf": { status: "failed", error: "Task cancelled by user" },
        "real-fail.pdf": { status: "failed", error: "Parsing error" },
      },
    });

    renderWithProviders(<TaskErrorContent task={task} />);

    // The summary line includes both counts
    expect(screen.getByText(/1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/1 cancelled/)).toBeInTheDocument();
  });
});
