import { useMutation, useQueryClient } from "@tanstack/react-query";
import { TASKS_QUERY_KEY, type Task } from "@/app/api/queries/useGetTasksQuery";
import { apiClient } from "@/lib/api-client";

export function useDeleteTaskMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (taskId: string) => {
      const res = await apiClient.delete(`/tasks/${taskId}`);
      if (res.status === 404) return;
      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          (body as { error?: string }).error ?? "Failed to delete task",
        );
      }
    },
    onSuccess: (_data, taskId) => {
      queryClient.setQueryData<Task[]>([...TASKS_QUERY_KEY], (old) =>
        (old ?? []).filter((t) => t.task_id !== taskId),
      );
    },
    onError: (error) => {
      console.error("Delete task failed:", error);
    },
  });
}

export function useDeleteAllTerminalTasksMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<string[]> => {
      const res = await apiClient.delete<{ deleted_ids?: unknown }>("/tasks");
      if (res.status === 404) return [];
      if (res.status < 200 || res.status >= 300) {
        const body = res.data;
        throw new Error(
          (body as { error?: string }).error ?? "Failed to delete tasks",
        );
      }
      const body = res.data;
      if (
        !Array.isArray(body.deleted_ids) ||
        !body.deleted_ids.every((id: unknown) => typeof id === "string")
      ) {
        throw new Error(
          `Unexpected response shape: deleted_ids=${JSON.stringify(body.deleted_ids)}`,
        );
      }
      return body.deleted_ids;
    },
    onSuccess: (deletedIds) => {
      const deleted = new Set(deletedIds);
      queryClient.setQueryData<Task[]>([...TASKS_QUERY_KEY], (old) =>
        (old ?? []).filter((t) => !deleted.has(t.task_id)),
      );
    },
    onError: (error) => {
      console.error("Delete all tasks failed:", error);
    },
  });
}
