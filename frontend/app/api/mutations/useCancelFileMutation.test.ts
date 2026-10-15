import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import { useCancelFileMutation } from "./useCancelFileMutation";

describe("useCancelFileMutation", () => {
  it("calls the cancel file API endpoint with correct parameters", async () => {
    const seen = vi.fn();
    server.use(
      http.post(
        "/api/tasks/test-task-123/files/cancel",
        async ({ request }) => {
          seen(await request.json());
          return HttpResponse.json({
            status: "cancelled",
            task_id: "test-task-123",
            file_path: "test.pdf",
          });
        },
      ),
    );

    const { result } = renderHook(() => useCancelFileMutation(), {
      wrapper: createQueryWrapper(),
    });

    result.current.mutate({ taskId: "test-task-123", filePath: "test.pdf" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toHaveBeenCalledWith({ file_path: "test.pdf" });
  });

  it("handles error when file cannot be cancelled", async () => {
    server.use(
      http.post("/api/tasks/test-task-123/files/cancel", () =>
        HttpResponse.json(
          { error: "File not found or cannot be cancelled" },
          { status: 404 },
        ),
      ),
    );

    const { result } = renderHook(() => useCancelFileMutation(), {
      wrapper: createQueryWrapper(),
    });

    result.current.mutate({ taskId: "test-task-123", filePath: "test.pdf" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "File not found or cannot be cancelled",
    );
  });

  it("handles network errors gracefully", async () => {
    server.use(
      http.post(
        "/api/tasks/test-task-123/files/cancel",
        () => new HttpResponse("not JSON", { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useCancelFileMutation(), {
      wrapper: createQueryWrapper(),
    });

    result.current.mutate({ taskId: "test-task-123", filePath: "test.pdf" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to cancel file");
  });
});
