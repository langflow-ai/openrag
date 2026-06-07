import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import { parseTimestampMs } from "@/lib/time-utils";

export const INGESTION_STALE_THRESHOLD_SEC = 35 * 60;
export const INGESTION_SLOW_THRESHOLD_SEC = 10 * 60;

export type IngestionHealth = "ok" | "slow" | "stale";

export function getFailedFileEntries(
  task: Task,
): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {}).filter(
    ([, fileInfo]) =>
      fileInfo?.status === "failed" || fileInfo?.status === "error",
  );
}

export function hasFailedFileEntries(task: Task): boolean {
  if ((task.failed_files ?? 0) > 0) {
    return true;
  }
  return getFailedFileEntries(task).length > 0;
}

export function isTerminalFailedTask(task: Task): boolean {
  return task.status === "failed" || task.status === "error";
}

export function isCompletedWithFailures(task: Task): boolean {
  return task.status === "completed" && hasFailedFileEntries(task);
}

export function isFailureLikeTask(task: Task): boolean {
  return isTerminalFailedTask(task) || isCompletedWithFailures(task);
}

export function formatTaskProgress(task: Task) {
  const total = task.total_files || 0;
  const processed = task.processed_files || 0;
  const successful = task.successful_files || 0;
  const failed = task.failed_files || 0;
  const running = task.running_files || 0;
  const pending = task.pending_files || 0;

  if (total > 0) {
    return {
      basic: `${processed}/${total} files`,
      basicEs: `${processed}/${total} archivos`,
      detailed: {
        total,
        processed,
        successful,
        failed,
        running,
        pending,
        remaining: total - processed,
      },
    };
  }
  return null;
}

export function formatDuration(seconds?: number): string | null {
  if (seconds === undefined || seconds === null || seconds < 0) return null;

  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
  }
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

/** Spanish short label for ingestion UI: "12 min", "45 s". */
export function formatDurationEs(seconds?: number): string | null {
  if (seconds === undefined || seconds === null || seconds < 0) return null;

  if (seconds < 60) {
    return `${Math.round(seconds)} s`;
  }
  if (seconds < 3600) {
    const mins = Math.max(1, Math.floor(seconds / 60));
    return `${mins} min`;
  }
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return mins > 0 ? `${hours} h ${mins} min` : `${hours} h`;
}

export function getElapsedSeconds(entry?: TaskFileEntry): number {
  if (!entry) return 0;
  if (
    typeof entry.duration_seconds === "number" &&
    entry.duration_seconds >= 0
  ) {
    return entry.duration_seconds;
  }
  const created = entry.created_at
    ? parseTimestampMs(String(entry.created_at))
    : null;
  const updated = entry.updated_at
    ? parseTimestampMs(String(entry.updated_at))
    : null;
  if (created !== null && updated !== null && updated >= created) {
    return (updated - created) / 1000;
  }
  if (created !== null) {
    return (Date.now() - created) / 1000;
  }
  return 0;
}

export function getIngestionHealth(elapsedSec: number): IngestionHealth {
  if (elapsedSec >= INGESTION_STALE_THRESHOLD_SEC) return "stale";
  if (elapsedSec >= INGESTION_SLOW_THRESHOLD_SEC) return "slow";
  return "ok";
}

export function getRunningFileEntries(
  task: Task,
): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {}).filter(
    ([, fileInfo]) =>
      fileInfo?.status === "running" ||
      fileInfo?.status === "processing" ||
      fileInfo?.status === "pending",
  );
}

export function getTaskFileEntryForFilename(
  task: Task,
  filename?: string,
): TaskFileEntry | undefined {
  if (!filename || !task.files) return undefined;
  const entries = Object.values(task.files);
  return entries.find((entry) => entry.filename === filename);
}

export function getActiveTaskElapsedSeconds(task: Task): number {
  const running = getRunningFileEntries(task);
  if (running.length > 0) {
    return Math.max(...running.map(([, entry]) => getElapsedSeconds(entry)));
  }
  if (typeof task.duration_seconds === "number" && task.duration_seconds >= 0) {
    return task.duration_seconds;
  }
  const created = parseTimestampMs(task.created_at);
  if (created !== null) {
    return (Date.now() - created) / 1000;
  }
  return 0;
}
