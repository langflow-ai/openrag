import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createQueryWrapper } from "@/test-utils/render";
import { useCancelFileMutation } from "./useCancelFileMutation";

describe("useCancelFileMutation", () => {
  it("calls the cancel file API endpoint with correct parameters", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            status: "cancelled",
            task_id: "test-task-123",
            file_path: "test.pdf",
          }),
      } as Response),
    );

    const { result } = renderHook(() => useCancelFileMutation(), {
      wrapper: createQueryWrapper(),
    });

    result.current.mutate({ taskId: "test-task-123", filePath: "test.pdf" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/tasks/test-task-123/files/cancel",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: "test.pdf" }),
      }),
    );
  });

  it("handles error when file cannot be cancelled", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        json: () =>
          Promise.resolve({ error: "File not found or cannot be cancelled" }),
      } as Response),
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
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        json: () => Promise.reject(new Error("Network error")),
      } as Response),
    );

    const { result } = renderHook(() => useCancelFileMutation(), {
      wrapper: createQueryWrapper(),
    });

    result.current.mutate({ taskId: "test-task-123", filePath: "test.pdf" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to cancel file");
  });
});
