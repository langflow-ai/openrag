/**
 * Tests for useDeleteTaskMutation and useDeleteAllTerminalTasksMutation.
 *
 * Network is mocked via MSW (per-test overrides). react-query wiring, URL,
 * response.ok handling, cache updates, and error paths all stay under test.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import {
  useDeleteAllTerminalTasksMutation,
  useDeleteTaskMutation,
} from "@/app/api/mutations/useDeleteTaskMutation";
import { TASKS_QUERY_KEY, type Task } from "@/app/api/queries/useGetTasksQuery";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, createTestQueryClient } from "@/test-utils/render";

// ─── helpers ──────────────────────────────────────────────────────────────────

function makeTask(partial: Partial<Task> = {}): Task {
  return {
    task_id: "aaaaaaaa-0000-0000-0000-000000000000",
    status: "completed",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:01Z",
    ...partial,
  };
}

// ─── useDeleteTaskMutation ────────────────────────────────────────────────────

describe("useDeleteTaskMutation", () => {
  it("calls DELETE /api/tasks/:id and removes the task from cache on success", async () => {
    const taskId = "task-001";
    server.use(
      http.delete(
        `/api/tasks/${taskId}`,
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    // Use a longer gcTime so cache entries survive the test without an active observer.
    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    // Seed the cache with the task to be deleted.
    queryClient.setQueryData<Task[]>(
      ["tasks", "enhanced"],
      [makeTask({ task_id: taskId })],
    );

    const { result } = renderHook(() => useDeleteTaskMutation(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => {
      result.current.mutate(taskId);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // onSuccess calls setQueryData, removing the deleted task from the cache list.
    await waitFor(() => {
      const cached = queryClient.getQueryData<Task[]>(["tasks", "enhanced"]);
      expect(Array.isArray(cached)).toBe(true);
      expect(cached!.find((t) => t.task_id === taskId)).toBeUndefined();
    });
  });

  it("treats a 404 as success without throwing", async () => {
    const taskId = "missing-task";
    server.use(
      http.delete(
        `/api/tasks/${taskId}`,
        () => new HttpResponse(null, { status: 404 }),
      ),
    );

    const queryClient = createTestQueryClient();
    queryClient.setQueryData<Task[]>([...TASKS_QUERY_KEY], []);

    const { result } = renderHook(() => useDeleteTaskMutation(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => {
      result.current.mutate(taskId);
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.error).toBeNull();
  });

  it("throws an error and sets isError when the response is not ok", async () => {
    const taskId = "bad-task";
    server.use(
      http.delete(`/api/tasks/${taskId}`, () =>
        HttpResponse.json({ error: "server exploded" }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useDeleteTaskMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => {
      result.current.mutate(taskId);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("server exploded");
  });

  it("falls back to default error message when body has no error field", async () => {
    const taskId = "no-body-task";
    server.use(
      http.delete(`/api/tasks/${taskId}`, () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useDeleteTaskMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => {
      result.current.mutate(taskId);
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to delete task");
  });
});

// ─── useDeleteAllTerminalTasksMutation ────────────────────────────────────────

describe("useDeleteAllTerminalTasksMutation", () => {
  it("calls DELETE /api/tasks, returns deleted IDs, and removes them from cache", async () => {
    const keepId = "keep-001";
    const deleteId = "del-001";
    server.use(
      http.delete("/api/tasks", () =>
        HttpResponse.json({ deleted_ids: [deleteId] }),
      ),
    );

    // Use a longer gcTime so cache entries survive the test without an active observer.
    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    queryClient.setQueryData<Task[]>(
      ["tasks", "enhanced"],
      [makeTask({ task_id: keepId }), makeTask({ task_id: deleteId })],
    );

    const { result } = renderHook(() => useDeleteAllTerminalTasksMutation(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // onSuccess calls setQueryData, keeping only the non-deleted tasks.
    await waitFor(() => {
      const cached = queryClient.getQueryData<Task[]>(["tasks", "enhanced"]);
      expect(Array.isArray(cached)).toBe(true);
      expect(cached!.find((t) => t.task_id === deleteId)).toBeUndefined();
      expect(cached!.find((t) => t.task_id === keepId)).toBeDefined();
    });
  });

  it("throws when deleted_ids is not an array of strings", async () => {
    server.use(
      http.delete("/api/tasks", () =>
        HttpResponse.json({ deleted_ids: [1, 2, 3] }),
      ),
    );

    const { result } = renderHook(() => useDeleteAllTerminalTasksMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(/Unexpected response shape/);
  });

  it("treats a 404 as a no-op returning empty array", async () => {
    server.use(
      http.delete("/api/tasks", () => new HttpResponse(null, { status: 404 })),
    );

    const { result } = renderHook(() => useDeleteAllTerminalTasksMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("throws when the response is not ok", async () => {
    server.use(
      http.delete("/api/tasks", () =>
        HttpResponse.json({ error: "forbidden" }, { status: 403 }),
      ),
    );

    const { result } = renderHook(() => useDeleteAllTerminalTasksMutation(), {
      wrapper: createQueryWrapper(),
    });

    act(() => {
      result.current.mutate();
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("forbidden");
  });
});
