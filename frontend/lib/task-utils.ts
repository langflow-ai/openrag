import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  buildRowStatusLabel,
  inferFailedPipelineStep,
  resolveTaskFileError,
} from "@/lib/task-error-display";

export const ALL_TASK_FILE_TYPES = "__all__";
export const ALL_TASK_STATUS_CATEGORIES = "__all__";

export type TaskFileStatusCategory =
  | "completed"
  | "system_error"
  | "indexing"
  | "partial";

export type TaskFileNameSort = "asc" | "desc";

export type TaskFileFilterOptions = {
  search?: string;
  fileType?: string | typeof ALL_TASK_FILE_TYPES;
  statusCategory?: TaskFileStatusCategory | typeof ALL_TASK_STATUS_CATEGORIES;
  task?: Task;
};

interface TaskFileCategoryContext {
  taskHasFailures: boolean;
  successfulFileCount: number;
}

export function isTaskFileCompleted(fileInfo: TaskFileEntry): boolean {
  return fileInfo.status === "completed";
}

export function isTaskFileFailed(fileInfo: TaskFileEntry): boolean {
  return fileInfo.status === "failed" || fileInfo.status === "error";
}

export function getTaskFileDialogStatusLabel(
  fileInfo: TaskFileEntry,
  taskError?: string,
): string {
  if (isTaskFileFailed(fileInfo)) {
    return buildRowStatusLabel(
      inferFailedPipelineStep(
        fileInfo,
        resolveTaskFileError(fileInfo, taskError),
      ),
    );
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
export function getFileExtensionFromName(filename: string): string {
  const trimmed = filename.trim();
  const dotIndex = trimmed.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex === trimmed.length - 1) {
    return "";
  }
  return trimmed.slice(dotIndex + 1).toLowerCase();
}

export function getTaskFileTypeKey(
  filePath: string,
  fileInfo: TaskFileEntry,
): string {
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

function getTaskFileCategoryContext(task: Task): TaskFileCategoryContext {
  return {
    taskHasFailures: hasFailedFileEntries(task),
    successfulFileCount: getSuccessfulFileCount(task),
  };
}

/**
 * Maps a file to a dialog filter chip bucket.
 * Completed files in a mixed task (failures + successes) use `partial`, not `completed`.
 */
export function getTaskFileStatusCategory(
  fileInfo: TaskFileEntry,
  task: Task,
  context: TaskFileCategoryContext = getTaskFileCategoryContext(task),
): TaskFileStatusCategory {
  if (isTaskFileFailed(fileInfo)) {
    return "system_error";
  }

  const status = fileInfo.status ?? "pending";
  if (status === "pending" || status === "running" || status === "processing") {
    return "indexing";
  }

  if (status === "completed") {
    if (context.taskHasFailures && context.successfulFileCount > 0) {
      return "partial";
    }
    return "completed";
  }

  return "indexing";
}

export function countTaskFilesByCategory(
  task: Task,
): Record<TaskFileStatusCategory, number> {
  const counts: Record<TaskFileStatusCategory, number> = {
    completed: 0,
    system_error: 0,
    indexing: 0,
    partial: 0,
  };
  const context = getTaskFileCategoryContext(task);

  for (const [, fileInfo] of getTaskFileEntries(task)) {
    const category = getTaskFileStatusCategory(fileInfo, task, context);
    counts[category] += 1;
  }

  return counts;
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
  const categoryContext = options.task
    ? getTaskFileCategoryContext(options.task)
    : undefined;

  return entries.filter(([filePath, fileInfo]) => {
    if (fileType !== ALL_TASK_FILE_TYPES) {
      const typeKey = getTaskFileTypeKey(filePath, fileInfo);
      if (typeKey !== fileType) {
        return false;
      }
    }

    if (
      options.task &&
      statusCategory !== ALL_TASK_STATUS_CATEGORIES &&
      categoryContext &&
      getTaskFileStatusCategory(fileInfo, options.task, categoryContext) !==
        statusCategory
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
