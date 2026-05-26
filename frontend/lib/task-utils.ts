import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";

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
