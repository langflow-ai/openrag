import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  buildRowStatusLabel,
  normalizeFailurePhase,
} from "@/lib/task-error-display";

export const ALL_TASK_FILE_TYPES = "__all__";
export const ALL_TASK_STATUS_CATEGORIES = "__all__";

export type TaskFileStatusCategory =
  | "completed"
  | "warning"
  | "system_error"
  | "indexing";

export type TaskFileNameSort = "asc" | "desc";

export type TaskFileFilterOptions = {
  search?: string;
  fileType?: string | typeof ALL_TASK_FILE_TYPES;
  statusCategory?: TaskFileStatusCategory | typeof ALL_TASK_STATUS_CATEGORIES;
  task?: Task;
};

function isTaskFileCompleted(fileInfo: TaskFileEntry): boolean {
  return fileInfo.status === "completed";
}

export function isTaskFileFailed(fileInfo: TaskFileEntry): boolean {
  return fileInfo.status === "failed" || fileInfo.status === "error";
}

export function isTaskFileWarning(fileInfo: TaskFileEntry): boolean {
  return fileInfo.status === "skipped";
}

export function getTaskFileDialogStatusLabel(
  fileInfo: TaskFileEntry,
  taskError?: string,
): string {
  if (isTaskFileFailed(fileInfo)) {
    const failurePhase = normalizeFailurePhase(fileInfo.failure_phase);
    if (failurePhase) {
      return buildRowStatusLabel(failurePhase);
    }
    if (fileInfo.user_facing_message?.trim()) {
      return "Failed";
    }
    return buildRowStatusLabel("unknown");
  }
  if (isTaskFileWarning(fileInfo)) {
    return "Warning";
  }
  if (isTaskFileCompleted(fileInfo)) {
    return "Complete";
  }
  return "Processing";
}

export function getTaskFileName(
  filePath: string,
  fileInfo: TaskFileEntry,
): string {
  return fileInfo.filename || filePath.split("/").pop() || filePath;
}

/** Lowercase extension without dot, or empty string when none. */
function getFileExtensionFromName(filename: string): string {
  const trimmed = filename.trim();
  const dotIndex = trimmed.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === trimmed.length - 1) {
    return "";
  }
  return trimmed.slice(dotIndex + 1).toLowerCase();
}

function getTaskFileTypeKey(filePath: string, fileInfo: TaskFileEntry): string {
  const extension = getFileExtensionFromName(
    getTaskFileName(filePath, fileInfo),
  );
  return extension || "unknown";
}

export function getTaskFileEntries(task: Task): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {});
}

export function getTaskFileTypes(task: Task): string[] {
  const types = new Set(
    getTaskFileEntries(task).map(([path, entry]) =>
      getTaskFileTypeKey(path, entry),
    ),
  );
  return Array.from(types).sort((a, b) => a.localeCompare(b));
}

export function formatTaskFileTypeLabel(fileType: string): string {
  if (fileType === "unknown") {
    return "Unknown";
  }
  return fileType.toUpperCase();
}

export function isTaskFileRetryable(fileInfo: TaskFileEntry): boolean {
  return fileInfo.actionable_by === "RETRYABLE";
}

export function getRetryableFileEntries(
  task: Task,
): Array<[string, TaskFileEntry]> {
  return getTaskFileEntries(task).filter(([, fileInfo]) =>
    isTaskFileRetryable(fileInfo),
  );
}

export function getRetryableFilePaths(
  entries: Array<[string, TaskFileEntry]>,
): string[] {
  return entries
    .filter(([, fileInfo]) => isTaskFileRetryable(fileInfo))
    .map(([filePath]) => filePath);
}

export function countRetryIngestionFiles(task: Task): number {
  return getTaskFileEntries(task).filter(([, fileInfo]) =>
    isTaskFileRetryable(fileInfo),
  ).length;
}

/** Maps a file to a dialog filter chip bucket (aligned with per-file status labels). */
function getTaskFileStatusCategory(
  fileInfo: TaskFileEntry,
): TaskFileStatusCategory {
  if (isTaskFileFailed(fileInfo)) {
    return "system_error";
  }
  if (isTaskFileWarning(fileInfo)) {
    return "warning";
  }

  const status = fileInfo.status ?? "pending";
  if (status === "pending" || status === "running" || status === "processing") {
    return "indexing";
  }

  if (status === "completed") {
    return "completed";
  }

  return "indexing";
}

export function countTaskFileEntriesByCategory(
  entries: Array<[string, TaskFileEntry]>,
): Record<TaskFileStatusCategory, number> {
  const counts: Record<TaskFileStatusCategory, number> = {
    completed: 0,
    warning: 0,
    system_error: 0,
    indexing: 0,
  };

  for (const [, fileInfo] of entries) {
    const category = getTaskFileStatusCategory(fileInfo);
    counts[category] += 1;
  }

  return counts;
}

function countTaskFilesByCategory(
  task: Task,
): Record<TaskFileStatusCategory, number> {
  return countTaskFileEntriesByCategory(getTaskFileEntries(task));
}

export function sortTaskFileEntries(
  entries: Array<[string, TaskFileEntry]>,
  direction: TaskFileNameSort = "asc",
): Array<[string, TaskFileEntry]> {
  const sorted = [...entries].sort(([pathA, infoA], [pathB, infoB]) =>
    getTaskFileName(pathA, infoA).localeCompare(
      getTaskFileName(pathB, infoB),
      undefined,
      { sensitivity: "base" },
    ),
  );
  return direction === "asc" ? sorted : sorted.reverse();
}

export function filterTaskFileEntries(
  entries: Array<[string, TaskFileEntry]>,
  options: TaskFileFilterOptions,
): Array<[string, TaskFileEntry]> {
  const query = options.search?.trim().toLowerCase() ?? "";
  const fileType = options.fileType ?? ALL_TASK_FILE_TYPES;
  const statusCategory = options.statusCategory ?? ALL_TASK_STATUS_CATEGORIES;

  return entries.filter(([filePath, fileInfo]) => {
    if (fileType !== ALL_TASK_FILE_TYPES) {
      const typeKey = getTaskFileTypeKey(filePath, fileInfo);
      if (typeKey !== fileType) {
        return false;
      }
    }

    if (
      statusCategory !== ALL_TASK_STATUS_CATEGORIES &&
      getTaskFileStatusCategory(fileInfo) !== statusCategory
    ) {
      return false;
    }

    if (query) {
      const name = getTaskFileName(filePath, fileInfo);
      if (!name.toLowerCase().includes(query)) {
        return false;
      }
    }

    return true;
  });
}

function getFailedFileEntries(task: Task): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {}).filter(([, fileInfo]) =>
    isTaskFileFailed(fileInfo),
  );
}

export function getWarningFileEntries(
  task: Task,
): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {}).filter(([, fileInfo]) =>
    isTaskFileWarning(fileInfo),
  );
}

export function getTaskIssueFileEntries(
  task: Task,
): Array<[string, TaskFileEntry]> {
  return Object.entries(task.files || {}).filter(
    ([, fileInfo]) => isTaskFileFailed(fileInfo) || isTaskFileWarning(fileInfo),
  );
}

export function hasFailedFileEntries(task: Task): boolean {
  if ((task.failed_files ?? 0) > 0) {
    return true;
  }
  return getFailedFileEntries(task).length > 0;
}

export function hasIssueFileEntries(task: Task): boolean {
  if ((task.failed_files ?? 0) > 0) {
    return true;
  }
  return getTaskIssueFileEntries(task).length > 0;
}

export function isTerminalFailedTask(task: Task): boolean {
  return task.status === "failed" || task.status === "error";
}

function isCompletedWithFailures(task: Task): boolean {
  return task.status === "completed" && hasFailedFileEntries(task);
}

export function getSuccessfulFileCount(task: Task): number {
  if (typeof task.successful_files === "number") {
    return task.successful_files;
  }
  return Object.values(task.files || {}).filter(
    (fileInfo) => fileInfo?.status === "completed",
  ).length;
}

export function getFailedFileCount(task: Task): number {
  if (typeof task.failed_files === "number") {
    return task.failed_files;
  }
  return getFailedFileEntries(task).length;
}

/** Completed task with failures and no successful files — treat as failed, not partial success. */
export function isCompletedTotalFailure(task: Task): boolean {
  return isCompletedWithFailures(task) && getSuccessfulFileCount(task) === 0;
}

export function isFailureLikeTask(task: Task): boolean {
  return isTerminalFailedTask(task) || isCompletedWithFailures(task);
}

export function isTaskInProgressStatus(status: Task["status"]): boolean {
  return (
    status === "pending" || status === "running" || status === "processing"
  );
}

export function isTerminalTaskStatus(status: Task["status"]): boolean {
  return (
    status === "completed" ||
    status === "failed" ||
    status === "error" ||
    status === "skipped"
  );
}

/** True when a task has just entered a terminal status. */
export function didTaskReachTerminalState(
  previousTask: Task | undefined,
  currentTask: Task,
): boolean {
  return (
    !!previousTask &&
    !isTerminalTaskStatus(previousTask.status) &&
    isTerminalTaskStatus(currentTask.status)
  );
}

/** True when a task has just transitioned to completed. */
export function didTaskReachCompleted(
  previousTask: Task | undefined,
  currentTask: Task,
): boolean {
  return (
    !!previousTask &&
    previousTask.status !== "completed" &&
    currentTask.status === "completed"
  );
}

/**
 * File paths present on the previous enhanced-list payload but omitted now.
 * The enhanced list drops completed files from `files` while a task is still running.
 */
/** Stable overlay key before the backend temp path is known. */
function pendingTaskFileSourceUrl(taskId: string, filename: string): string {
  return `pending:${taskId}:${filename}`;
}

function isPendingTaskFileSourceUrl(sourceUrl: string): boolean {
  return sourceUrl.startsWith("pending:");
}

export function findTaskFileOverlayIndex(
  files: Array<{ task_id: string; source_url: string; filename: string }>,
  taskId: string,
  filePath: string,
  fileName: string,
): number {
  const pendingUrl = pendingTaskFileSourceUrl(taskId, fileName);
  return files.findIndex(
    (f) =>
      f.task_id === taskId &&
      (f.source_url === filePath ||
        f.source_url === pendingUrl ||
        (f.filename === fileName && isPendingTaskFileSourceUrl(f.source_url))),
  );
}

export function getEnhancedListDisappearedFilePaths(
  currentTask: Task,
  previousTask: Task,
): string[] {
  const currentKeys = new Set(Object.keys(currentTask.files ?? {}));
  return Object.keys(previousTask.files ?? {}).filter(
    (filePath) => !currentKeys.has(filePath),
  );
}

interface ProcessingFileOverlay {
  task_id: string;
  source_url: string;
  status: "active" | "failed" | "processing";
  error?: string;
}

/**
 * Promote local processing overlays when the enhanced list omits completed files.
 * Pass `disappearedPaths` while the task is in progress; omit it when the task completes
 * to finalize every remaining processing file for that task.
 */
export function finalizeProcessingOverlaysForEnhancedTask<
  T extends ProcessingFileOverlay,
>(prevFiles: T[], currentTask: Task, disappearedPaths?: string[]): T[] {
  const pathsFilter =
    disappearedPaths === undefined ? null : new Set(disappearedPaths);
  let changed = false;

  const updated = prevFiles.map((file) => {
    if (file.task_id !== currentTask.task_id) {
      return file;
    }
    if (pathsFilter !== null && !pathsFilter.has(file.source_url)) {
      return file;
    }
    // Overlays can still be "failed" until the list poll sees a retry as running.
    if (file.status !== "processing" && file.status !== "failed") {
      return file;
    }

    const entry = currentTask.files?.[file.source_url];
    if (entry && isTaskFileFailed(entry)) {
      if (file.status === "failed") {
        const error =
          typeof entry.error === "string" && entry.error.trim().length > 0
            ? entry.error.trim()
            : file.error;
        if (error === file.error) {
          return file;
        }
      }
      changed = true;
      const error =
        typeof entry.error === "string" && entry.error.trim().length > 0
          ? entry.error.trim()
          : file.error;
      return { ...file, status: "failed" as const, error };
    }

    // Left the enhanced list (completed files are omitted) or task finished.
    changed = true;
    return { ...file, status: "active" as const, error: undefined };
  });

  return changed ? (updated as T[]) : prevFiles;
}
