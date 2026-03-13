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

export function isFailureLikeTask(task: Task): boolean {
  return isTerminalFailedTask(task) || isCompletedWithFailures(task);
}
