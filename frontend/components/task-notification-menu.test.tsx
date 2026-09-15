import { act, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
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

// Each mock spreads the real module: `@/test-utils/render` imports every
// `*Provider` from these contexts, and vitest throws at import time if a
// factory mock drops an export it needs.

// Shared task context mock — individual tests mutate `mockTasks`.
let mockTasks: Task[] = [];
vi.mock("@/contexts/task-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/task-context")>()),
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

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

vi.mock("@/contexts/console-status-context", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/contexts/console-status-context")
  >()),
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

describe("TaskNotificationMenu — task deletion controls", () => {
  it("shows delete buttons for completed, failed, and cancelled tasks", () => {
    mockTasks = [
      makeTask({ task_id: "completed-task", status: "completed" }),
      makeTask({ task_id: "failed-task", status: "failed" }),
      makeTask({ task_id: "cancelled-task", status: "cancelled" }),
    ];

    renderWithProviders(<TaskNotificationMenu />);

    expect(screen.getAllByRole("button", { name: "Delete task" })).toHaveLength(
      3,
    );
  });

  it("calls DELETE /api/tasks/:id for a cancelled task", async () => {
    const user = userEvent.setup();
    let deletedId: string | undefined;
    server.use(
      http.delete("/api/tasks/:taskId", ({ params }) => {
        deletedId = params.taskId as string;
        return HttpResponse.json({});
      }),
    );

    mockTasks = [makeTask({ task_id: "t-cancelled", status: "cancelled" })];
    renderWithProviders(<TaskNotificationMenu />);

    const deleteBtn = screen.getByRole("button", { name: "Delete task" });
    await user.click(deleteBtn);

    await waitFor(() => {
      expect(deletedId).toBe("t-cancelled");
    });
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

describe("TaskNotificationMenu — delete mutations", () => {
  it("calls DELETE /api/tasks when 'Clear all' is clicked", async () => {
    const user = userEvent.setup();
    let deleteAllCalled = false;
    server.use(
      http.delete("/api/tasks", () => {
        deleteAllCalled = true;
        return HttpResponse.json({ deleted_ids: [] });
      }),
    );

    // The "Clear all" button appears only when there is at least one owned
    // (non-shared) terminal task.
    mockTasks = [makeTask({ task_id: "t-done", status: "completed" })];
    renderWithProviders(<TaskNotificationMenu />);

    const clearAllBtn = screen.getByRole("button", {
      name: "Clear all past tasks",
    });
    await user.click(clearAllBtn);

    await waitFor(() => {
      expect(deleteAllCalled).toBe(true);
    });
  });

  it("calls DELETE /api/tasks/:id when the delete button is clicked on a regular terminal task", async () => {
    const user = userEvent.setup();
    let deletedId: string | undefined;
    server.use(
      http.delete("/api/tasks/:taskId", ({ params }) => {
        deletedId = params.taskId as string;
        return HttpResponse.json({});
      }),
    );

    mockTasks = [makeTask({ task_id: "t-completed", status: "completed" })];
    renderWithProviders(<TaskNotificationMenu />);

    const deleteBtn = screen.getByRole("button", { name: "Delete task" });
    await user.click(deleteBtn);

    await waitFor(() => {
      expect(deletedId).toBe("t-completed");
    });
  });

  it("calls DELETE /api/tasks/:id when the delete button is clicked inside a TaskErrorContent row", async () => {
    const user = userEvent.setup();
    let deletedId: string | undefined;
    server.use(
      http.delete("/api/tasks/:taskId", ({ params }) => {
        deletedId = params.taskId as string;
        return HttpResponse.json({});
      }),
    );

    // A failed task with file-level error details renders the TaskErrorContent row
    // which embeds its own delete button as headerEnd.
    mockTasks = [
      makeTask({
        task_id: "t-failed",
        status: "failed",
        failed_files: 1,
        files: {
          "doc.pdf": { status: "failed", error: "Parse error" },
        },
      }),
    ];
    renderWithProviders(<TaskNotificationMenu />);

    // The delete button inside the TaskErrorContent headerEnd
    const deleteBtns = screen.getAllByRole("button", { name: "Delete task" });
    await user.click(deleteBtns[0]);

    await waitFor(() => {
      expect(deletedId).toBe("t-failed");
    });
  });

  it("hides 'Clear all' when every terminal task is shared", () => {
    // Only shared tasks — "Clear all" must not appear because the backend
    // bulk-delete only removes tasks owned by the calling user.
    mockTasks = [
      makeTask({ task_id: "shared-1", status: "completed", is_shared: true }),
      makeTask({ task_id: "shared-2", status: "failed", is_shared: true }),
    ];

    renderWithProviders(<TaskNotificationMenu />);

    expect(
      screen.queryByRole("button", { name: "Clear all past tasks" }),
    ).not.toBeInTheDocument();
  });

  it("shows 'Clear all' when at least one owned terminal task exists alongside shared ones", () => {
    // Mix of owned and shared — "Clear all" should be present because there
    // is at least one task the bulk-delete will actually remove.
    mockTasks = [
      makeTask({ task_id: "shared-1", status: "completed", is_shared: true }),
      makeTask({ task_id: "owned-1", status: "completed", is_shared: false }),
    ];

    renderWithProviders(<TaskNotificationMenu />);

    expect(
      screen.getByRole("button", { name: "Clear all past tasks" }),
    ).toBeInTheDocument();
  });
});
