import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";
import { apiClient } from "@/lib/api-client";

export interface CancelTaskRequest {
  taskId: string;
}

export interface CancelTaskResponse {
  status: string;
  task_id: string;
}

async function cancelTask(
  variables: CancelTaskRequest,
): Promise<CancelTaskResponse> {
  const response = await apiClient.post<CancelTaskResponse>(
    `/tasks/${variables.taskId}/cancel`,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorData = response.data as unknown as { error?: string };
    throw new Error(errorData.error || "Failed to cancel task");
  }

  return response.data;
}

export const useCancelTaskMutation = (
  options?: Omit<
    UseMutationOptions<CancelTaskResponse, Error, CancelTaskRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  const { onSuccess, onError, onSettled, ...restOptions } = options ?? {};

  return useMutation({
    mutationFn: cancelTask,
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
