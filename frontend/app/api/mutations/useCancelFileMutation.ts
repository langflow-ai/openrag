import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";

export interface CancelFileRequest {
  taskId: string;
  filePath: string;
}

export interface CancelFileResponse {
  status: string;
  task_id: string;
  file_path: string;
}

async function cancelFile(
  variables: CancelFileRequest,
): Promise<CancelFileResponse> {
  const response = await fetch(`/api/tasks/${variables.taskId}/files/cancel`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      file_path: variables.filePath,
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.error || "Failed to cancel file");
  }

  return response.json();
}

export const useCancelFileMutation = (
  options?: Omit<
    UseMutationOptions<CancelFileResponse, Error, CancelFileRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  const { onSuccess, onError, onSettled, ...restOptions } = options ?? {};

  return useMutation({
    mutationFn: cancelFile,
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
