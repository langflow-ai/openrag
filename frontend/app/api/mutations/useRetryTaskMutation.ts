import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";

export interface RetryTaskRequest {
  taskId: string;
  /** When set, only these task file paths are retried. Omit to retry all failed RETRYABLE files. */
  filePaths?: string[];
}

export interface RetryTaskSkippedFile {
  file_path: string;
  filename?: string;
  reason:
    | "not_retryable"
    | "source_file_missing"
    | "file_not_in_task"
    | "not_failed"
    | string;
}

export interface RetryTaskResponse {
  task_id: string;
  retried: number;
  skipped: RetryTaskSkippedFile[];
  status: string;
  message?: string;
  error?: string;
}

export const useRetryTaskMutation = (
  options?: Omit<
    UseMutationOptions<RetryTaskResponse, Error, RetryTaskRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function retryTask(
    variables: RetryTaskRequest,
  ): Promise<RetryTaskResponse> {
    const body = JSON.stringify(
      variables.filePaths != null ? { file_paths: variables.filePaths } : {},
    );

    const response = await fetch(`/api/tasks/${variables.taskId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    const payload = (await response
      .json()
      .catch(() => ({}))) as RetryTaskResponse;

    if (!response.ok) {
      throw new Error(
        payload.message || payload.error || "Failed to retry task files",
      );
    }

    return payload;
  }

  const { onSuccess, onError, onSettled, ...restOptions } = options ?? {};

  return useMutation({
    mutationFn: retryTask,
    ...restOptions,
    onSuccess: (data, variables, onMutateResult, context) => {
      queryClient.invalidateQueries({ queryKey: [...TASKS_QUERY_KEY] });
      queryClient.invalidateQueries({
        queryKey: taskDetailQueryKey(variables.taskId),
      });
      onSuccess?.(data, variables, onMutateResult, context);
    },
    onError,
    onSettled,
  });
};
