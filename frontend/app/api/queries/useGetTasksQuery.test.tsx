import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { type Task, useGetTasksQuery } from "./useGetTasksQuery";

/**
 * Reference pattern for testing a query hook.
 *
 * Nothing here is mocked with `vi.mock`. The real `getTasks` runs, so the URL,
 * the `response.ok` branch, the `data.tasks || []` unwrapping, and the
 * react-query wiring are all genuinely under test — MSW only answers the
 * network underneath.
 */

function task(overrides: Partial<Task> = {}): Task {
  return {
    task_id: "t1",
    status: "completed",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:01:00Z",
    ...overrides,
  };
}

describe("useGetTasksQuery", () => {
  it("resolves a relative /api path through MSW and unwraps tasks", async () => {
    server.use(
      http.get("/api/tasks/enhanced", () =>
        HttpResponse.json({ tasks: [task({ task_id: "abc" })] }),
      ),
    );

    const { result } = renderHook(() => useGetTasksQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].task_id).toBe("abc");
  });

  it("returns [] when the payload has no tasks key", async () => {
    server.use(http.get("/api/tasks/enhanced", () => HttpResponse.json({})));

    const { result } = renderHook(() => useGetTasksQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });

  it("surfaces an error when the backend returns 500", async () => {
    server.use(
      http.get(
        "/api/tasks/enhanced",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useGetTasksQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to fetch tasks");
  });

  it("surfaces an error when the backend returns 401", async () => {
    server.use(
      http.get(
        "/api/tasks/enhanced",
        () => new HttpResponse(null, { status: 401 }),
      ),
    );

    const { result } = renderHook(() => useGetTasksQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
