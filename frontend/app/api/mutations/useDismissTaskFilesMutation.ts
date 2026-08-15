import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";

export interface DismissTaskFilesRequest {
  taskId: string;
  /** Task file paths of terminal failed files to remove from the task. */
  filePaths: string[];
}

export interface DismissTaskFilesSkippedFile {
  file_path: string;
  filename?: string;
  reason: "file_not_in_task" | "not_failed" | string;
}

export interface DismissTaskFilesResponse {
  task_id: string;
  dismissed: number;
  skipped: DismissTaskFilesSkippedFile[];
  status: string;
  message?: string;
  error?: string;
}

async function dismissTaskFiles(
  variables: DismissTaskFilesRequest,
): Promise<DismissTaskFilesResponse> {
  const response = await fetch(`/api/tasks/${variables.taskId}/files/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_paths: variables.filePaths }),
  });

  const payload = (await response
    .json()
    .catch(() => ({}))) as DismissTaskFilesResponse;

  if (!response.ok) {
    throw new Error(
      payload.message || payload.error || "Failed to dismiss task files",
    );
  }

  return payload;
}

export const useDismissTaskFilesMutation = (
  options?: Omit<
    UseMutationOptions<
      DismissTaskFilesResponse,
      Error,
      DismissTaskFilesRequest
    >,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  const { onSuccess, onError, onSettled, ...restOptions } = options ?? {};

  return useMutation({
    mutationFn: dismissTaskFiles,
    ...restOptions,
    onSuccess: (data, variables, onMutateResult, context) => {
      queryClient.invalidateQueries({ queryKey: [...TASKS_QUERY_KEY] });
      queryClient.invalidateQueries({
        queryKey: taskDetailQueryKey(variables.taskId),
      });
      queryClient.invalidateQueries({ queryKey: ["listFiles"] });
      queryClient.invalidateQueries({ queryKey: ["search"] });
      onSuccess?.(data, variables, onMutateResult, context);
    },
    onError,
    onSettled,
  });
};
