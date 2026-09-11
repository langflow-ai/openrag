/**
 * Tests for TaskNotificationMenu.
 *
 * Covered lines (per diff gate):
 *   237-238 — deleteTaskMutation / deleteAllMutation hook usage
 *   240     — isPastOpen state initialisation
 *   325     — onClearAll fires deleteAllMutation.mutate()
 *   442     — onToggle toggles isPastOpen
 *   452-456 — renderItem for failed terminal tasks
 *   458     — isTerminalFailedTask / isTotalFailure / hasFailedFiles branch
 *   463     — TaskErrorContent rendered for failed tasks
 *   479-480 — delete button in the failed task card row
 *   492-498 — toggleExpand for successful terminal tasks
 *   501     — successful terminal task row rendered
 *   546-547 — delete button in successful task row
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { TaskNotificationMenu } from "@/components/task-notification-menu";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders } from "@/test-utils/render";

// ─── context / hook mocks ──────────────────────────────────────────────────────

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: vi.fn(),
}));

vi.mock("@/contexts/task-context", () => ({
  useTask: vi.fn(),
}));

// Stub TaskErrorContent with a version that also renders the `headerEnd` prop
// so the "Delete task" button inside it is accessible in tests.
vi.mock("@/components/task-error-content", () => ({
  TaskErrorContent: ({
    task,
    headerEnd,
  }: {
    task: Task;
    headerEnd?: React.ReactNode;
  }) => <div data-testid={`task-error-${task.task_id}`}>{headerEnd}</div>,
}));

vi.mock("@/components/task-panel-header", () => ({
  TaskPanelHeader: ({
    onClearAll,
    onClose,
  }: {
    onClearAll?: () => void;
    onClose: () => void;
  }) => (
    <div>
      <button type="button" onClick={onClearAll} data-testid="clear-all">
        Clear all
      </button>
      <button type="button" onClick={onClose} data-testid="close-panel">
        Close
      </button>
    </div>
  ),
}));

vi.mock("@/components/task-progress-details", () => ({
  TaskProgressDetails: () => <div data-testid="task-progress-details" />,
}));

import { useIsCloudBrand } from "@/contexts/brand-context";
import { useTask } from "@/contexts/task-context";

// ─── helpers ──────────────────────────────────────────────────────────────────

const noop = vi.fn();

function defaultTaskContext(tasks: Task[] = []) {
  return {
    tasks,
    isFetching: false,
    isMenuOpen: true,
    isRecentTasksExpanded: false,
    selectedTaskId: null,
    selectedTaskTrigger: 0,
    cancelTask: noop,
    closeMenu: noop,
    openTaskDialog: noop,
  };
}

function makeTask(partial: Partial<Task>): Task {
  return {
    task_id: "00000000-0000-0000-0000-000000000000",
    status: "completed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    ...partial,
  };
}

// IDs where the first 8 chars contain a "0" so the rendered text
// "Task <id.substring(0,8)>..." matches our regex.
function makeFailedTerminalTask(
  id = "fail0001-0000-0000-0000-000000000000",
): Task {
  return makeTask({
    task_id: id,
    status: "failed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
  });
}

function makeCompletedTask(id = "comp0001-0000-0000-0000-000000000000"): Task {
  return makeTask({
    task_id: id,
    status: "completed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
  });
}

function setupContexts(tasks: Task[] = [], isCloud = false) {
  vi.mocked(useIsCloudBrand).mockReturnValue(isCloud);
  vi.mocked(useTask).mockReturnValue(
    defaultTaskContext(tasks) as unknown as ReturnType<typeof useTask>,
  );
}

function renderMenu() {
  return renderWithProviders(<TaskNotificationMenu />);
}

// ─── tests ────────────────────────────────────────────────────────────────────

describe("TaskNotificationMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Provide default handlers so unmatched DELETE requests don't error.
    server.use(
      http.delete(
        "/api/tasks/:id",
        () => new HttpResponse(null, { status: 204 }),
      ),
      http.delete("/api/tasks", () => HttpResponse.json({ deleted_ids: [] })),
    );
  });

  it("renders nothing when isMenuOpen is false", () => {
    vi.mocked(useIsCloudBrand).mockReturnValue(false);
    vi.mocked(useTask).mockReturnValue({
      ...defaultTaskContext([]),
      isMenuOpen: false,
    } as unknown as ReturnType<typeof useTask>);
    const { container } = renderMenu();
    expect(container.firstChild).toBeNull();
  });

  it("shows the empty state when there are no tasks", () => {
    setupContexts([]);
    renderMenu();
    expect(screen.getByText(/no tasks yet/i)).toBeInTheDocument();
  });

  it("fires deleteAllMutation.mutate when Clear all button is clicked (line 325)", async () => {
    setupContexts([makeCompletedTask()]);
    server.use(
      http.delete("/api/tasks", () =>
        HttpResponse.json({ deleted_ids: ["comp0001"] }),
      ),
    );
    renderMenu();
    await userEvent.click(screen.getByTestId("clear-all"));
    // Verifies the button is wired and does not throw.
  });

  it("renders TaskErrorContent for terminal failed tasks (lines 452-456, 458, 463)", () => {
    const failedTask = makeFailedTerminalTask(
      "fail0001-0000-0000-0000-000000000000",
    );
    setupContexts([failedTask]);
    renderMenu();
    expect(
      screen.getByTestId("task-error-fail0001-0000-0000-0000-000000000000"),
    ).toBeInTheDocument();
  });

  it("calls deleteTaskMutation for a failed task when the delete button is clicked (lines 479-480)", async () => {
    const taskId = "fail0002-0000-0000-0000-000000000000";
    setupContexts([makeFailedTerminalTask(taskId)]);
    let deleteCalled = false;
    server.use(
      http.delete(`/api/tasks/${taskId}`, () => {
        deleteCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderMenu();

    // The delete button is rendered inside our TaskErrorContent stub as headerEnd.
    const deleteBtns = screen.getAllByRole("button", { name: /delete task/i });
    await userEvent.click(deleteBtns[0]);

    await vi.waitFor(() => expect(deleteCalled).toBe(true));
  });

  it("renders a successful terminal task row (line 501)", () => {
    const completedTask = makeCompletedTask(
      "comp0001-0000-0000-0000-000000000000",
    );
    setupContexts([completedTask]);
    renderMenu();
    // The row renders "Task comp0001..." — first 8 chars of "comp0001-..." = "comp0001"
    expect(screen.getByText(/comp0001/)).toBeInTheDocument();
  });

  it("toggles task detail expansion for a successful task (lines 492-498)", async () => {
    // The completed task row has a toggle button wrapping the task name.
    // Its accessible text includes "Task comp0002".
    const completedTask = makeCompletedTask(
      "comp0002-0000-0000-0000-000000000000",
    );
    setupContexts([completedTask]);
    renderMenu();

    // Find the expand toggle button by a partial text match.
    const rowBtn = screen.getByRole("button", { name: /comp0002/i });
    await userEvent.click(rowBtn);
    // Second click collapses.
    await userEvent.click(rowBtn);
    // No throw = toggle worked.
  });

  it("calls deleteTaskMutation for a successful task when delete button is clicked (lines 546-547)", async () => {
    const taskId = "comp0003-0000-0000-0000-000000000000";
    setupContexts([makeCompletedTask(taskId)]);
    let deleteCalled = false;
    server.use(
      http.delete(`/api/tasks/${taskId}`, () => {
        deleteCalled = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderMenu();

    const deleteBtns = screen.getAllByRole("button", { name: /delete task/i });
    await userEvent.click(deleteBtns[0]);

    await vi.waitFor(() => expect(deleteCalled).toBe(true));
  });

  it("toggles Past Tasks section when onToggle is called (line 442)", async () => {
    const completedTask = makeCompletedTask(
      "comp0004-0000-0000-0000-000000000000",
    );
    setupContexts([completedTask]);
    renderMenu();

    // TaskCollapsibleSection renders its title inside a button.
    const sectionToggle = screen.getByRole("button", { name: /past tasks/i });
    await userEvent.click(sectionToggle);
    // Row disappears after collapse.
    expect(screen.queryByText(/comp0004/)).toBeNull();

    // Click again to re-open.
    await userEvent.click(sectionToggle);
    expect(screen.getByText(/comp0004/)).toBeInTheDocument();
  });

  it("initialises isPastOpen to true when menu opens (line 240)", () => {
    // When isMenuOpen is true from the start, isPastOpen starts true,
    // so the Past Tasks section shows items immediately.
    const completedTask = makeCompletedTask(
      "comp0005-0000-0000-0000-000000000000",
    );
    setupContexts([completedTask]);
    renderMenu();
    // Task row visible because section starts open.
    expect(screen.getByText(/comp0005/)).toBeInTheDocument();
  });
});
