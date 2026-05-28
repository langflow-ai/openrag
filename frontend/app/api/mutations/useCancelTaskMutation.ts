import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

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
    onSuccess: (data, variables, context) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"], exact: false });
      onSuccess?.(data, variables, context);
    },
    onError,
    onSettled,
  });
};
