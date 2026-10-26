import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";
import { apiClient } from "@/lib/api-client";

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
  const response = await apiClient.post<CancelFileResponse>(
    `/tasks/${variables.taskId}/files/cancel`,
    { file_path: variables.filePath },
  );

  if (response.status < 200 || response.status >= 300) {
    const errorData = response.data as unknown as { error?: string };
    throw new Error(errorData.error || "Failed to cancel file");
  }

  return response.data;
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
