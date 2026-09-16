import { describe, expect, it } from "vitest";
import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  countTaskFileEntriesByCategory,
  finalizeProcessingOverlaysForEnhancedTask,
  getDeletedAtSourceMessage,
  getTaskFileDialogStatusLabel,
  getTaskIssueFileEntries,
  isDeletedAtSourceFile,
  isTaskFileWarning,
  isTerminalTaskStatus,
} from "./task-utils";

function entry(overrides: Partial<TaskFileEntry> = {}): TaskFileEntry {
  return { status: "failed", ...overrides };
}

describe("getTaskFileDialogStatusLabel — cancellation branch", () => {
  it("returns 'Cancelled' for a file cancelled by the user via error message", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ error: "Task cancelled by user" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for a file with failure_phase 'cancelled'", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ failure_phase: "cancelled" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for file-level cancel error message", () => {
    expect(
      getTaskFileDialogStatusLabel(entry({ error: "File cancelled by user" })),
    ).toBe("Cancelled");
  });

  it("returns 'Cancelled' for 'file processing task cancelled' error", () => {
    expect(
      getTaskFileDialogStatusLabel(
        entry({ error: "file processing task cancelled" }),
      ),
    ).toBe("Cancelled");
  });

  it("returns a phase-based label for a non-cancelled failed file", () => {
    const label = getTaskFileDialogStatusLabel(
      entry({ failure_phase: "parsing" }),
    );
    expect(label).toBe("Parsing issue");
  });
});

describe("countTaskFileEntriesByCategory — cancelled bucket", () => {
  it("categorises a file with 'task cancelled by user' error as cancelled", () => {
    const counts = countTaskFileEntriesByCategory([
      [
        "file.pdf",
        entry({ status: "failed", error: "Task cancelled by user" }),
      ],
    ]);
    expect(counts.cancelled).toBe(1);
    expect(counts.system_error).toBe(0);
  });

  it("categorises a file with failure_phase 'cancelled' as cancelled", () => {
    const counts = countTaskFileEntriesByCategory([
      ["file.pdf", entry({ failure_phase: "cancelled" })],
    ]);
    expect(counts.cancelled).toBe(1);
    expect(counts.system_error).toBe(0);
  });

  it("categorises a non-cancelled failed file as system_error", () => {
    const counts = countTaskFileEntriesByCategory([
      ["file.pdf", entry({ failure_phase: "parsing" })],
    ]);
    expect(counts.system_error).toBe(1);
    expect(counts.cancelled).toBe(0);
  });
});

describe("deleted_at_source is successful cleanup, not a warning", () => {
  const deletedAtSource = entry({
    status: "completed",
    result: {
      reason: "deleted_at_source",
      message:
        "File no longer exists at source; removed from index (1 chunk(s) deleted).",
    },
  });

  it("does not classify a source-deleted file as a warning", () => {
    expect(isDeletedAtSourceFile(deletedAtSource)).toBe(true);
    expect(isTaskFileWarning(deletedAtSource)).toBe(false);
    expect(isTaskFileWarning(entry({ status: "skipped" }))).toBe(true);
  });

  it("still does not treat a leftover skipped source-deleted file as a warning", () => {
    expect(
      isTaskFileWarning(
        entry({
          status: "skipped",
          result: { reason: "deleted_at_source" },
        }),
      ),
    ).toBe(false);
  });

  it("labels a source-deleted file Removed and keeps the cleanup message", () => {
    expect(getTaskFileDialogStatusLabel(deletedAtSource)).toBe("Removed");
    expect(getDeletedAtSourceMessage(deletedAtSource)).toContain(
      "removed from index",
    );
    expect(getDeletedAtSourceMessage(entry({ status: "completed" }))).toBe(
      undefined,
    );
    expect(
      getDeletedAtSourceMessage(
        entry({
          status: "completed",
          result: { reason: "deleted_at_source", message: "   " },
        }),
      ),
    ).toBeUndefined();
  });

  it("buckets a source-deleted file as completed, not warning", () => {
    const counts = countTaskFileEntriesByCategory([
      ["gone.pdf", deletedAtSource],
    ]);
    expect(counts.completed).toBe(1);
    expect(counts.warning).toBe(0);
  });

  it("omits source-deleted files from the issue list", () => {
    const task: Task = {
      task_id: "t1",
      status: "completed",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T10:00:00Z",
      successful_files: 1,
      files: { "gone.pdf": deletedAtSource },
    };
    expect(getTaskIssueFileEntries(task)).toEqual([]);
  });

  it("drops processing overlays instead of promoting them to active", () => {
    const task: Task = {
      task_id: "task-1",
      status: "running",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T10:00:00Z",
      files: { "file-id-1": deletedAtSource },
    };
    const overlays = [
      {
        task_id: "task-1",
        source_url: "file-id-1",
        status: "processing" as const,
      },
      {
        task_id: "task-1",
        source_url: "other.pdf",
        status: "processing" as const,
      },
    ];

    const next = finalizeProcessingOverlaysForEnhancedTask(overlays, task, [
      "file-id-1",
    ]);

    expect(next).toEqual([
      {
        task_id: "task-1",
        source_url: "other.pdf",
        status: "processing",
      },
    ]);
  });

  it("drops source-deleted overlays when the whole task completes", () => {
    const task: Task = {
      task_id: "task-1",
      status: "completed",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T10:00:00Z",
      files: { "file-id-1": deletedAtSource },
    };
    const overlays = [
      {
        task_id: "task-1",
        source_url: "file-id-1",
        status: "processing" as const,
      },
    ];

    expect(finalizeProcessingOverlaysForEnhancedTask(overlays, task)).toEqual(
      [],
    );
  });

  it("leaves overlays for other tasks and already-active files unchanged", () => {
    const task: Task = {
      task_id: "task-1",
      status: "running",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T10:00:00Z",
      files: { "file-id-1": deletedAtSource },
    };
    const overlays = [
      {
        task_id: "other-task",
        source_url: "file-id-1",
        status: "processing" as const,
      },
      {
        task_id: "task-1",
        source_url: "already.pdf",
        status: "active" as const,
      },
    ];

    expect(
      finalizeProcessingOverlaysForEnhancedTask(overlays, task, ["file-id-1"]),
    ).toEqual(overlays);
  });

  it("promotes a disappeared completed ingest overlay to active", () => {
    const task: Task = {
      task_id: "task-1",
      status: "running",
      created_at: "2026-09-16T10:00:00Z",
      updated_at: "2026-09-16T10:00:00Z",
      files: {},
    };
    const overlays = [
      {
        task_id: "task-1",
        source_url: "ingested.pdf",
        status: "processing" as const,
      },
    ];

    expect(
      finalizeProcessingOverlaysForEnhancedTask(overlays, task, [
        "ingested.pdf",
      ]),
    ).toEqual([
      {
        task_id: "task-1",
        source_url: "ingested.pdf",
        status: "active",
        error: undefined,
      },
    ]);
  });
});

describe("isTerminalTaskStatus — cancelled status", () => {
  it("treats 'cancelled' as a terminal status", () => {
    expect(isTerminalTaskStatus("cancelled")).toBe(true);
  });

  it("does not treat in-progress statuses as terminal", () => {
    expect(isTerminalTaskStatus("pending")).toBe(false);
    expect(isTerminalTaskStatus("running")).toBe(false);
    expect(isTerminalTaskStatus("processing")).toBe(false);
  });
});
