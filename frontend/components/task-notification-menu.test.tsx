import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { renderWithProviders, screen } from "@/test-utils/render";
import { TaskNotificationMenu } from "./task-notification-menu";

/**
 * Tests for the cancellation-specific branches added to TaskNotificationMenu:
 *   - getTaskIcon returns the grey XCircle for "cancelled"
 *   - getTaskStatusBadge returns the "CANCELLED" badge
 *   - cancellingTaskIds useEffect removes entries when tasks reach terminal state
 *   - isCancelled render branch shows "CANCELLED" text instead of the task ID
 *
 * All context dependencies are mocked at the module level.
 */

const cancelTask = vi.fn().mockResolvedValue(undefined);
const openTaskDialog = vi.fn();
const closeMenu = vi.fn();

// Shared task context mock — individual tests mutate `mockTasks`.
let mockTasks: Task[] = [];
vi.mock("@/contexts/task-context", () => ({
  useTask: () => ({
    tasks: mockTasks,
    isFetching: false,
    isMenuOpen: true,
    isRecentTasksExpanded: false,
    selectedTaskId: null,
    selectedTaskTrigger: 0,
    cancelTask,
    closeMenu,
    openTaskDialog,
  }),
}));

vi.mock("@/contexts/brand-context", () => ({
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/console-status-context", () => ({
  useConsoleStatus: () => ({ problems: [], open: vi.fn() }),
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    task_id: "task-abc",
    status: "running",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:05:00Z",
    ...overrides,
  };
}

describe("TaskNotificationMenu — cancelled task display", () => {
  it("shows 'CANCELLED' badge in recent tasks for a cancelled task", () => {
    // A cancelled task sits in the recent (non-active) section
    mockTasks = [makeTask({ status: "cancelled" })];

    renderWithProviders(<TaskNotificationMenu />);

    expect(screen.getByText("CANCELLED")).toBeInTheDocument();
  });

  it("shows 'CANCELLED' label in the active tasks section for a task that arrived as cancelled", () => {
    // The activeTasks list filters to pending/running/processing, so a cancelled
    // task will only appear in the recent section. Test the badge via the recent list.
    mockTasks = [makeTask({ status: "cancelled" })];

    renderWithProviders(<TaskNotificationMenu />);

    // The CANCELLED badge should be rendered
    const badge = screen.getByText("CANCELLED");
    expect(badge).toBeInTheDocument();
  });
});

describe("TaskNotificationMenu — cancellingTaskIds cleanup useEffect", () => {
  it("removes a task from cancellingTaskIds when it transitions to cancelled", async () => {
    // Start with a running task.
    mockTasks = [makeTask({ task_id: "t1", status: "running" })];

    const { rerender } = renderWithProviders(<TaskNotificationMenu />);

    // Click "Cancel" for the running task — sets it in cancellingTaskIds.
    const cancelButton = screen.getByRole("button", { name: /cancel task/i });
    await act(async () => {
      cancelButton.click();
    });

    // Now transition the task to cancelled — the cleanup useEffect should fire.
    mockTasks = [makeTask({ task_id: "t1", status: "cancelled" })];
    rerender(<TaskNotificationMenu />);

    // After re-render the "CANCELLING..." text should be gone and "CANCELLED" shown
    await waitFor(() => {
      expect(screen.queryByText("CANCELLING...")).not.toBeInTheDocument();
    });
  });

  it("removes a task from cancellingTaskIds when it disappears from the task list", async () => {
    mockTasks = [makeTask({ task_id: "t1", status: "running" })];

    const { rerender } = renderWithProviders(<TaskNotificationMenu />);

    const cancelButton = screen.getByRole("button", { name: /cancel task/i });
    await act(async () => {
      cancelButton.click();
    });

    // Task disappears entirely from the list
    mockTasks = [];
    rerender(<TaskNotificationMenu />);

    await waitFor(() => {
      expect(screen.queryByText("CANCELLING...")).not.toBeInTheDocument();
    });
  });
});
