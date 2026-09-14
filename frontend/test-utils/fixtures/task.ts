/**
 * Fixtures for `Task` / `TaskFileEntry`.
 *
 * `Task` has 13 optional fields and `files` is a keyed map, so building one
 * inline costs more than the assertion it supports. These builders default to
 * a coherent single-file task and let a test name only what it is testing.
 *
 * Typed against the app's own exported interfaces so a change to the response
 * shape breaks `npm run typecheck` here rather than silently passing.
 */
import type {
  Task,
  TaskFileEntry,
  TasksResponse,
} from "@/app/api/queries/useGetTasksQuery";

/** Fixed so tests never depend on wall-clock ordering. */
const CREATED_AT = "2026-01-01T00:00:00Z";
const UPDATED_AT = "2026-01-01T00:00:05Z";

export function makeTaskFile(
  overrides: Partial<TaskFileEntry> = {},
): TaskFileEntry {
  return {
    status: "completed",
    filename: "report.pdf",
    phase: "complete",
    created_at: CREATED_AT,
    updated_at: UPDATED_AT,
    ...overrides,
  };
}

/**
 * A failed file with the classification fields the enhanced API adds. Split
 * out because `lib/task-error-display.ts` and `lib/task-utils.ts` branch on
 * `failure_phase` / `actionable_by`, and forgetting them yields a file that
 * looks failed but classifies as "unknown".
 */
export function makeFailedTaskFile(
  overrides: Partial<TaskFileEntry> = {},
): TaskFileEntry {
  return makeTaskFile({
    status: "failed",
    component: "docling",
    failure_phase: "parsing",
    actionable_by: "RETRYABLE",
    user_facing_message: "Could not parse the document.",
    error: "parse error",
    ...overrides,
  });
}

/**
 * Builds a task from a `path -> entry` map, deriving the file counts so they
 * agree with `files`. Pass counts explicitly only when testing what the UI
 * does with an inconsistent payload.
 */
export function makeTask(
  overrides: Partial<Task> & { files?: Record<string, TaskFileEntry> } = {},
): Task {
  const files = overrides.files ?? {
    "/data/report.pdf": makeTaskFile(),
  };
  const entries = Object.values(files);
  const isTerminal = (s: TaskFileEntry["status"]) =>
    s === "completed" || s === "skipped" || s === "failed" || s === "error";

  return {
    task_id: "task-1",
    status: "completed",
    created_at: CREATED_AT,
    updated_at: UPDATED_AT,
    total_files: entries.length,
    processed_files: entries.filter((f) => isTerminal(f.status)).length,
    successful_files: entries.filter((f) => f.status === "completed").length,
    failed_files: entries.filter(
      (f) => f.status === "failed" || f.status === "error",
    ).length,
    running_files: entries.filter(
      (f) => f.status === "running" || f.status === "processing",
    ).length,
    pending_files: entries.filter((f) => f.status === "pending").length,
    ...overrides,
    files,
  };
}

/** The GET /api/tasks/enhanced envelope. */
export function makeTasksResponse(tasks: Task[] = []): TasksResponse {
  return { tasks };
}
