import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { taskDetailQueryKey } from "@/app/api/queries/useGetTaskQuery";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";

export interface CancelTaskRequest {
  taskId: string;
}

export interface CancelTaskResponse {
  status: string;
  task_id: string;
}

export const useCancelTaskMutation = (
  options?: Omit<
    UseMutationOptions<CancelTaskResponse, Error, CancelTaskRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function cancelTask(
    variables: CancelTaskRequest,
  ): Promise<CancelTaskResponse> {
    const response = await fetch(`/api/tasks/${variables.taskId}/cancel`, {
      method: "POST",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to cancel task");
    }

    return response.json();
  }

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
