import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";
import { apiClient } from "@/lib/api-client";

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

async function retryTask(
  variables: RetryTaskRequest,
): Promise<RetryTaskResponse> {
  const response = await apiClient.post<RetryTaskResponse>(
    `/tasks/${variables.taskId}/retry`,
    variables.filePaths != null ? { file_paths: variables.filePaths } : {},
  );
  const payload = response.data;

  if (response.status < 200 || response.status >= 300) {
    throw new Error(
      payload.message || payload.error || "Failed to retry task files",
    );
  }

  return payload;
}

export const useRetryTaskMutation = (
  options?: Omit<
    UseMutationOptions<RetryTaskResponse, Error, RetryTaskRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

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
