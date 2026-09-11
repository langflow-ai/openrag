import { HttpResponse, http } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RetryTaskResponse } from "@/app/api/mutations/useRetryTaskMutation";
import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import { server } from "@/test-utils/msw/server";
import {
  act,
  createQueryWrapper,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import { useTaskDialog } from "./use-task-dialog";

/**
 * Phase 4 vertical slice: the task dialog's orchestration hook.
 *
 * What is real here: useGetTaskQuery, useRetryTaskMutation, the whole of
 * lib/task-utils, and the react-query cache. Requests are answered by MSW, so
 * URLs, `response.ok` branches, and payload shapes are all under test.
 *
 * What is mocked, and why:
 *   - `@/contexts/task-context` — `useTask()` throws outside a TaskProvider,
 *     and that provider is ~700 lines that fetch on mount. Mocking a *context*
 *     is fine; mocking `app/api/queries|mutations` is not (see AGENTS.md).
 *   - `sonner` — toasts are a side effect we assert on, not a thing to render.
 */

const markTaskFilesProcessing = vi.fn();
const refreshTasks = vi.fn().mockResolvedValue(undefined);

// `TaskProvider` is stubbed as a passthrough only because
// `test-utils/render.tsx` imports it from this module to build its provider
// stack. This test never mounts it, so a passthrough is honest — and cheaper
// than `importOriginal`, whose async factory resolves after the module graph
// has already bound the real export here.
vi.mock("@/contexts/task-context", () => ({
  useTask: () => ({ markTaskFilesProcessing, refreshTasks }),
  TaskProvider: ({ children }: { children: ReactNode }) => children,
}));

const toast = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
}));
vi.mock("sonner", () => ({ toast }));

const TASK_ID = "task-1";

function file(overrides: Partial<TaskFileEntry> = {}): TaskFileEntry {
  return { status: "completed", ...overrides };
}

function task(files: Record<string, TaskFileEntry>): Task {
  return {
    task_id: TASK_ID,
    status: "completed",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:05:00Z",
    files,
  };
}

/** Answers GET /api/tasks/:id/enhanced with `body`. */
function serveTask(body: Task | null, status = 200) {
  server.use(
    http.get(`/api/tasks/${TASK_ID}/enhanced`, () =>
      status === 200
        ? HttpResponse.json(body)
        : new HttpResponse(null, { status }),
    ),
  );
}

function renderDialog() {
  return renderHook(() => useTaskDialog(true, TASK_ID), {
    wrapper: createQueryWrapper(),
  });
}

/** Renders and waits for the task fetch to settle. */
async function renderLoaded() {
  const rendered = renderDialog();
  await waitFor(() => expect(rendered.result.current.isLoading).toBe(false));
  return rendered;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useTaskDialog", () => {
  describe("loading the task", () => {
    it("starts in a loading state and then exposes the task", async () => {
      serveTask(task({ "a.pdf": file() }));

      const { result } = renderDialog();
      expect(result.current.isLoading).toBe(true);

      await waitFor(() => expect(result.current.isLoading).toBe(false));
      expect(result.current.task?.task_id).toBe(TASK_ID);
      expect(result.current.fileEntries).toHaveLength(1);
    });

    it("reports an error when the backend fails", async () => {
      serveTask(null, 500);

      const { result } = renderDialog();

      await waitFor(() => expect(result.current.isError).toBe(true));
      expect(result.current.task).toBeUndefined();
    });

    it("treats a 404 as an empty task rather than an error", async () => {
      serveTask(null, 404);

      const { result } = await renderLoaded();

      expect(result.current.isError).toBe(false);
      expect(result.current.task).toBeUndefined();
      expect(result.current.fileEntries).toEqual([]);
    });
  });

  describe("filtering", () => {
    it("narrows entries by search text", async () => {
      serveTask(task({ "report.pdf": file(), "notes.docx": file() }));

      const { result } = await renderLoaded();
      expect(result.current.sortedEntries).toHaveLength(2);

      act(() => result.current.setSearch("report"));

      await waitFor(() => expect(result.current.sortedEntries).toHaveLength(1));
      expect(result.current.sortedEntries[0][0]).toBe("report.pdf");
    });

    it("derives the available file types from the task", async () => {
      serveTask(task({ "a.pdf": file(), "b.docx": file(), "c.pdf": file() }));

      const { result } = await renderLoaded();

      expect(result.current.fileTypes.sort()).toEqual(["docx", "pdf"]);
    });

    it("falls back to all file types when the selected type is absent", async () => {
      serveTask(task({ "a.pdf": file() }));

      const { result } = await renderLoaded();
      act(() => result.current.setFileType("xlsx"));

      // activeFileType, not the raw state, is what the hook exposes.
      await waitFor(() => expect(result.current.fileType).toBe("__all__"));
    });

    it("counts entries by status category", async () => {
      serveTask(
        task({
          "ok.pdf": file({ status: "completed" }),
          "bad.pdf": file({ status: "failed" }),
          "skip.pdf": file({ status: "skipped" }),
        }),
      );

      const { result } = await renderLoaded();

      expect(result.current.categoryCounts).toMatchObject({
        completed: 1,
        warning: 1,
      });
    });
  });

  describe("sorting", () => {
    it("toggles name sort between asc and desc", async () => {
      serveTask(task({ "a.pdf": file(), "b.pdf": file() }));

      const { result } = await renderLoaded();
      expect(result.current.nameSort).toBe("asc");
      expect(result.current.sortedEntries.map(([p]) => p)).toEqual([
        "a.pdf",
        "b.pdf",
      ]);

      act(() => result.current.toggleNameSort());

      await waitFor(() => expect(result.current.nameSort).toBe("desc"));
      expect(result.current.sortedEntries.map(([p]) => p)).toEqual([
        "b.pdf",
        "a.pdf",
      ]);
    });
  });

  describe("selection", () => {
    it("toggles a single path on and off", async () => {
      serveTask(
        task({
          "a.pdf": file({ status: "failed", actionable_by: "RETRYABLE" }),
        }),
      );

      const { result } = await renderLoaded();

      act(() => result.current.toggleSelectedPath("a.pdf"));
      await waitFor(() => expect(result.current.selectedCount).toBe(1));

      act(() => result.current.toggleSelectedPath("a.pdf"));
      await waitFor(() => expect(result.current.selectedCount).toBe(0));
    });

    it("selects and clears all visible retryable paths", async () => {
      serveTask(
        task({
          "a.pdf": file({ status: "failed", actionable_by: "RETRYABLE" }),
          "b.pdf": file({ status: "failed", actionable_by: "RETRYABLE" }),
          "done.pdf": file({ status: "completed" }),
        }),
      );

      const { result } = await renderLoaded();

      act(() => result.current.toggleSelectAllVisible());
      await waitFor(() =>
        expect(result.current.allSelectableSelected).toBe(true),
      );
      // The completed file is not selectable.
      expect(result.current.selectedCount).toBe(2);

      act(() => result.current.toggleSelectAllVisible());
      await waitFor(() => expect(result.current.selectedCount).toBe(0));
    });
  });

  describe("retry", () => {
    const retryable = {
      "a.pdf": file({ status: "failed", actionable_by: "RETRYABLE" }),
    };

    /** Builds a full RetryTaskResponse so fixtures stay faithful to the type. */
    function retryResponse(
      overrides: Partial<RetryTaskResponse> = {},
    ): RetryTaskResponse {
      return {
        task_id: TASK_ID,
        retried: 0,
        skipped: [],
        status: "completed",
        ...overrides,
      };
    }

    function serveRetry(body: RetryTaskResponse | null, status = 200) {
      server.use(
        http.post(`/api/tasks/${TASK_ID}/retry`, () =>
          status === 200
            ? HttpResponse.json(body)
            : new HttpResponse(null, { status }),
        ),
      );
    }

    it("retries every retryable file and reports success", async () => {
      serveTask(task(retryable));
      serveRetry(retryResponse({ retried: 1 }));

      const { result } = await renderLoaded();
      expect(result.current.retryableCount).toBe(1);

      await act(async () => {
        await result.current.handleRetryAll();
      });

      expect(markTaskFilesProcessing).toHaveBeenCalledWith(TASK_ID, ["a.pdf"]);
      expect(toast.success).toHaveBeenCalledWith(
        "Retry started",
        expect.objectContaining({
          description: "1 file(s) queued for ingestion",
        }),
      );
      expect(result.current.retryingTarget).toBeNull();
    });

    it("warns when files were skipped because the source is missing", async () => {
      serveTask(task(retryable));
      serveRetry(
        retryResponse({
          skipped: [{ file_path: "a.pdf", reason: "source_file_missing" }],
        }),
      );

      const { result } = await renderLoaded();
      await act(async () => {
        await result.current.handleRetryAll();
      });

      expect(toast.warning).toHaveBeenCalledWith(
        "Some files could not be retried",
        expect.objectContaining({
          description: expect.stringContaining("need to be uploaded again"),
        }),
      );
      expect(toast.success).not.toHaveBeenCalled();
    });

    it("refreshes tasks and surfaces an error toast when retry fails", async () => {
      serveTask(task(retryable));
      serveRetry(null, 500);

      const { result } = await renderLoaded();
      await act(async () => {
        await result.current.handleRetryAll();
      });

      expect(refreshTasks).toHaveBeenCalled();
      expect(toast.error).toHaveBeenCalledWith(
        "Retry failed",
        expect.objectContaining({ description: expect.any(String) }),
      );
      expect(result.current.retryingTarget).toBeNull();
    });

    it("does nothing when there is nothing retryable", async () => {
      serveTask(task({ "done.pdf": file({ status: "completed" }) }));

      const { result } = await renderLoaded();
      expect(result.current.retryableCount).toBe(0);

      await act(async () => {
        await result.current.handleRetryAll();
      });

      expect(markTaskFilesProcessing).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
    });

    it("clears the selection after a successful retry", async () => {
      serveTask(task(retryable));
      serveRetry(retryResponse({ retried: 1 }));

      const { result } = await renderLoaded();
      act(() => result.current.toggleSelectedPath("a.pdf"));
      await waitFor(() => expect(result.current.selectedCount).toBe(1));

      await act(async () => {
        await result.current.handleRetrySelected();
      });

      await waitFor(() => expect(result.current.selectedCount).toBe(0));
    });
  });
});
