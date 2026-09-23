import { describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { TaskErrorContent } from "./task-error-content";

/**
 * Tests for the cancellation-specific branches added to TaskErrorContent:
 *   - isCancelledOnly derived from isFileCancelled
 *   - "Cancelled" status label
 *   - "cancelled" count in the summary line
 *   - early-return when all counts are zero
 *
 * Also covers the interaction handlers added in the same diff:
 *   - toggleAccordion (click, Enter, Space)
 *   - openTaskDialog button click (stopPropagation + openTaskDialog)
 *   - Accordion trigger stopPropagation
 *   - headerEnd stopPropagation span
 *
 * TaskErrorContent depends on useTask (for openTaskDialog) and useIsCloudBrand.
 * Both are mocked at the module level — the context providers are not needed
 * because we are testing component logic, not the context wiring.
 *
 * Each mock spreads the real module: `@/test-utils/render` imports every
 * `*Provider` from these contexts, and vitest throws at import time if a
 * factory mock drops an export it needs.
 */

// Hoist the spy so it is available inside the vi.mock factory below.
const { mockOpenTaskDialog } = vi.hoisted(() => ({
  mockOpenTaskDialog: vi.fn(),
}));

vi.mock("@/contexts/task-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/task-context")>()),
  useTask: () => ({ openTaskDialog: mockOpenTaskDialog }),
}));

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
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

describe("TaskErrorContent — interaction handlers", () => {
  function makeFailedTask(overrides: Partial<Task> = {}): Task {
    return {
      task_id: "task-interaction-1",
      status: "failed",
      created_at: "2026-09-08T10:00:00Z",
      updated_at: "2026-09-08T10:05:00Z",
      failed_files: 1,
      files: {
        "doc.pdf": { status: "failed", error: "Parse error" },
      },
      ...overrides,
    };
  }

  it("toggles accordion open/closed when header row is clicked", async () => {
    const user = userEvent.setup();

    renderWithProviders(<TaskErrorContent task={makeFailedTask()} />);

    // The outer header div carries aria-expanded and acts as the toggle target.
    const expandableRow = document.querySelector(
      "[aria-expanded]",
    ) as HTMLElement;
    expect(expandableRow).not.toBeNull();
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");

    await user.click(expandableRow);
    expect(expandableRow.getAttribute("aria-expanded")).toBe("true");

    await user.click(expandableRow);
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");
  });

  it("toggles accordion open via Enter key on the header row", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TaskErrorContent task={makeFailedTask()} />);

    const expandableRow = document.querySelector(
      "[aria-expanded]",
    ) as HTMLElement;
    expandableRow.focus();
    await user.keyboard("{Enter}");
    expect(expandableRow.getAttribute("aria-expanded")).toBe("true");
  });

  it("toggles accordion open via Space key on the header row", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TaskErrorContent task={makeFailedTask()} />);

    const expandableRow = document.querySelector(
      "[aria-expanded]",
    ) as HTMLElement;
    expandableRow.focus();
    await user.keyboard(" ");
    expect(expandableRow.getAttribute("aria-expanded")).toBe("true");
  });

  it("calls openTaskDialog with the task id when the details button is clicked", async () => {
    const user = userEvent.setup();
    mockOpenTaskDialog.mockReset();

    renderWithProviders(<TaskErrorContent task={makeFailedTask()} />);

    await user.click(screen.getByRole("button", { name: "Open task details" }));

    expect(mockOpenTaskDialog).toHaveBeenCalledWith("task-interaction-1");
  });

  it("keyboard activation of task-details button calls openTaskDialog without toggling the accordion", async () => {
    const user = userEvent.setup();
    mockOpenTaskDialog.mockReset();

    renderWithProviders(<TaskErrorContent task={makeFailedTask()} />);

    const expandableRow = document.querySelector(
      "[aria-expanded]",
    ) as HTMLElement;
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");

    const detailsButton = screen.getByRole("button", {
      name: "Open task details",
    });
    detailsButton.focus();

    // Enter fires the button's click handler but must not bubble up to the
    // outer onKeyDown toggle.
    await user.keyboard("{Enter}");
    expect(mockOpenTaskDialog).toHaveBeenCalledWith("task-interaction-1");
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");

    mockOpenTaskDialog.mockReset();

    // Space likewise.
    await user.keyboard(" ");
    expect(mockOpenTaskDialog).toHaveBeenCalledWith("task-interaction-1");
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");
  });

  it("headerEnd click does not toggle the accordion (stopPropagation)", async () => {
    const user = userEvent.setup();
    const headerEndClick = vi.fn();

    renderWithProviders(
      <TaskErrorContent
        task={makeFailedTask()}
        headerEnd={
          <button
            type="button"
            onClick={headerEndClick}
            aria-label="header-end-action"
          >
            action
          </button>
        }
      />,
    );

    const expandableRow = document.querySelector(
      "[aria-expanded]",
    ) as HTMLElement;

    await user.click(screen.getByRole("button", { name: "header-end-action" }));

    expect(headerEndClick).toHaveBeenCalledTimes(1);
    // The wrapper <span> stopPropagation must prevent the accordion from toggling.
    expect(expandableRow.getAttribute("aria-expanded")).toBe("false");
  });
});
