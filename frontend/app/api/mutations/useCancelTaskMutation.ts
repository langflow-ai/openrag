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

  return useMutation({
    mutationFn: cancelTask,
    onSuccess: () => {
      // Invalidate tasks query to refresh the list
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    ...options,
  });
};
