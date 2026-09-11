import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";
import { server } from "@/test-utils/msw/server";
import {
  act,
  createTestQueryClient,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import { TaskProvider, useTask } from "./task-context";

/**
 * Unit tests for the cancellation-specific mutations and cache updates in
 * TaskProvider:
 *   - cancelTask() transitions the task to "cancelled" in the React Query cache
 *   - cancelFile() marks just the targeted file as failed/cancelled in the cache
 *   - allFailuresAreCancellations suppresses the "Task failed" toast
 *
 * Heavy provider deps (useAuth, useOnboardingState, analytics) are mocked so
 * the test does not spin up the full auth flow.
 */

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({ isAuthenticated: true, isNoAuthMode: false }),
}));

vi.mock("@/hooks/use-onboarding-state", () => ({
  useOnboardingState: () => ({ isOnboardingActive: false }),
}));

vi.mock("@/lib/analytics", () => ({
  trackProcessFailure: vi.fn(),
  trackProcessSuccess: vi.fn(),
}));

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));

// Suppress the TaskDialog import so we don't need to load Radix portal deps.
vi.mock("@/components/task-dialog", () => ({ default: () => null }));

// ── helpers ──────────────────────────────────────────────────────────────────

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    task_id: "task-1",
    status: "running",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:05:00Z",
    ...overrides,
  };
}

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <TaskProvider>{children}</TaskProvider>
      </QueryClientProvider>
    );
  };
}

function seedTasks(queryClient: QueryClient, tasks: Task[]) {
  queryClient.setQueryData([...TASKS_QUERY_KEY], tasks);
}

// ── tests ─────────────────────────────────────────────────────────────────────

describe("TaskProvider — cancelTask", () => {
  beforeEach(() => {
    toast.success.mockClear();
    toast.error.mockClear();
    toast.info.mockClear();
  });

  it("transitions the task to 'cancelled' and emits a success toast", async () => {
    const qc = createTestQueryClient();
    const task = makeTask({
      files: { "file.pdf": { status: "running", error: "" } },
    });
    seedTasks(qc, [task]);

    // The GET handler must return the task so the invalidateQueries refetch
    // does not silently reset the cache to [].
    server.use(
      http.get("/api/tasks/enhanced", () =>
        HttpResponse.json({ tasks: [{ ...task, status: "cancelled" }] }),
      ),
      http.post("/api/tasks/task-1/cancel", () =>
        HttpResponse.json({ status: "cancelled", task_id: "task-1" }),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.cancelTask("task-1");
    });

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Task cancelled",
        expect.objectContaining({
          description: "Task has been cancelled successfully",
        }),
      ),
    );
  });

  it("marks in-progress file entries as failed when the task is cancelled", async () => {
    const qc = createTestQueryClient();
    const task = makeTask({
      files: {
        "running.pdf": { status: "running", error: "" },
        "already-done.pdf": { status: "completed", error: "" },
      },
    });
    seedTasks(qc, [task]);

    // Capture the updater function that task-context passes to setQueryData so we
    // can evaluate the cache transformation in isolation, without a refetch race.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let capturedUpdater: ((old: Task[] | undefined) => Task[]) | undefined;
    const origSetQueryData = qc.setQueryData.bind(qc);
    vi.spyOn(qc, "setQueryData").mockImplementation((key, updater, options) => {
      if (typeof updater === "function") {
        capturedUpdater = updater as (old: Task[] | undefined) => Task[];
      }
      return origSetQueryData(key, updater, options);
    });

    server.use(
      http.get("/api/tasks/enhanced", () => HttpResponse.json({ tasks: [] })),
      http.post("/api/tasks/task-1/cancel", () =>
        HttpResponse.json({ status: "cancelled", task_id: "task-1" }),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.cancelTask("task-1");
    });

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(capturedUpdater).toBeDefined();

    // Apply the updater to the original task list to verify its transformation.
    const updated = capturedUpdater?.([task])?.find(
      (t) => t.task_id === "task-1",
    );
    expect(updated?.status).toBe("cancelled");
    expect(updated?.files?.["running.pdf"]?.status).toBe("failed");
    expect(updated?.files?.["running.pdf"]?.error).toBe(
      "Task cancelled by user",
    );
    expect(updated?.files?.["already-done.pdf"]?.status).toBe("completed");
  });

  it("shows an error toast when the cancel API fails", async () => {
    const qc = createTestQueryClient();
    seedTasks(qc, [makeTask()]);

    server.use(
      http.post("/api/tasks/task-1/cancel", () =>
        HttpResponse.json({ error: "Cannot cancel" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      try {
        await result.current.cancelTask("task-1");
      } catch {
        // expected
      }
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to cancel task",
        expect.objectContaining({ description: "Cannot cancel" }),
      ),
    );
  });
});

describe("TaskProvider — cancelFile", () => {
  beforeEach(() => {
    toast.success.mockClear();
    toast.error.mockClear();
    toast.info.mockClear();
  });

  it("marks the specified file as failed in the cache and emits a success toast", async () => {
    const qc = createTestQueryClient();
    const task = makeTask({
      files: {
        "target.pdf": { status: "running", error: "" },
        "other.pdf": { status: "running", error: "" },
      },
    });

    // Capture the updater so we can verify the transformation without a refetch race.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let capturedUpdater: ((old: Task[] | undefined) => Task[]) | undefined;
    const origSetQueryData = qc.setQueryData.bind(qc);
    vi.spyOn(qc, "setQueryData").mockImplementation((key, updater, options) => {
      if (typeof updater === "function") {
        capturedUpdater = updater as (old: Task[] | undefined) => Task[];
      }
      return origSetQueryData(key, updater, options);
    });

    seedTasks(qc, [task]);

    server.use(
      http.get("/api/tasks/enhanced", () => HttpResponse.json({ tasks: [] })),
      http.post("/api/tasks/task-1/files/cancel", () =>
        HttpResponse.json({
          status: "cancelled",
          task_id: "task-1",
          file_path: "target.pdf",
        }),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      await result.current.cancelFile("task-1", "target.pdf");
    });

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "File cancelled",
        expect.objectContaining({
          description: "File has been cancelled successfully",
        }),
      ),
    );

    expect(capturedUpdater).toBeDefined();
    const updated = capturedUpdater?.([task])?.find(
      (t) => t.task_id === "task-1",
    );
    expect(updated?.files?.["target.pdf"]?.status).toBe("failed");
    expect(updated?.files?.["target.pdf"]?.error).toBe(
      "File cancelled by user",
    );
    expect(updated?.files?.["other.pdf"]?.status).toBe("running");
  });

  it("shows an info toast when the file is already completed (404-style error)", async () => {
    const qc = createTestQueryClient();
    seedTasks(qc, [makeTask()]);

    server.use(
      http.post("/api/tasks/task-1/files/cancel", () =>
        HttpResponse.json(
          { error: "File not found or cannot be cancelled" },
          { status: 404 },
        ),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      try {
        await result.current.cancelFile("task-1", "done.pdf");
      } catch {
        // expected — mutation throws on error
      }
    });

    await waitFor(() =>
      expect(toast.info).toHaveBeenCalledWith(
        "File already completed",
        expect.any(Object),
      ),
    );
  });

  it("shows an error toast for unexpected cancelFile failures", async () => {
    const qc = createTestQueryClient();
    seedTasks(qc, [makeTask()]);

    server.use(
      http.post("/api/tasks/task-1/files/cancel", () =>
        HttpResponse.json({ error: "Internal server error" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    await act(async () => {
      try {
        await result.current.cancelFile("task-1", "file.pdf");
      } catch {
        // expected
      }
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to cancel file",
        expect.any(Object),
      ),
    );
  });
});

describe("TaskProvider — task completion with cancellations", () => {
  beforeEach(() => {
    toast.success.mockClear();
    toast.error.mockClear();
    toast.info.mockClear();
  });

  it("emits a 'File ingestion cancelled' info toast when all failures are cancellations", async () => {
    const qc = createTestQueryClient();

    // First request returns task as running (no previous tasks known).
    // Second request (after polling) returns it as completed with cancelled files.
    let callCount = 0;
    const runningTask: Task = makeTask({
      status: "running",
      files: { "file.pdf": { status: "running", error: "" } },
    });
    const completedTask: Task = {
      ...runningTask,
      status: "completed",
      successful_files: 0,
      failed_files: 1,
      files: {
        "file.pdf": { status: "failed", error: "Task cancelled by user" },
      },
    };

    server.use(
      http.get("/api/tasks/enhanced", () => {
        callCount++;
        return HttpResponse.json({
          tasks: [callCount === 1 ? runningTask : completedTask],
        });
      }),
    );

    renderHook(() => useTask(), { wrapper: wrapper(qc) });

    // Wait for the running task to be loaded first, then the completed one.
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(2), {
      timeout: 5000,
    });

    await waitFor(
      () =>
        expect(toast.info).toHaveBeenCalledWith(
          "File ingestion cancelled",
          expect.any(Object),
        ),
      { timeout: 5000 },
    );
  });

  it("maps 'failed' file status to 'cancelled' when the parent task transitions to cancelled", async () => {
    const qc = createTestQueryClient();

    // Task must transition running → cancelled for the useEffect to process files.
    let callCount = 0;
    const runningTask: Task = makeTask({
      task_id: "task-2",
      status: "running",
      files: { "file.pdf": { status: "running", error: "" } },
    });
    const cancelledTask: Task = {
      ...runningTask,
      status: "cancelled",
      files: {
        "file.pdf": { status: "failed", error: "Task cancelled by user" },
      },
    };

    server.use(
      http.get("/api/tasks/enhanced", () => {
        callCount++;
        return HttpResponse.json({
          tasks: [callCount === 1 ? runningTask : cancelledTask],
        });
      }),
    );

    const { result } = renderHook(() => useTask(), { wrapper: wrapper(qc) });

    // Wait for the running task to be seen, then the cancelled one.
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(2), {
      timeout: 5000,
    });

    // After the transition, the file overlay should have status "cancelled".
    await waitFor(
      () => {
        const f = result.current.files.find((f) => f.task_id === "task-2");
        expect(f?.status).toBe("cancelled");
      },
      { timeout: 5000 },
    );
  });
});
