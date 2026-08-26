import { useMutation, useQueryClient } from "@tanstack/react-query";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";

export function useDeleteTaskMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (taskId: string) => {
      const res = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete task");
    },
    onSuccess: (_data, taskId) => {
      queryClient.setQueryData([...TASKS_QUERY_KEY], (old: any[] | undefined) =>
        (old ?? []).filter((t) => t.task_id !== taskId),
      );
    },
  });
}

export function useDeleteAllTerminalTasksMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const res = await fetch("/api/tasks", { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete tasks");
    },
    onSuccess: () => {
      queryClient.setQueryData([...TASKS_QUERY_KEY], (old: any[] | undefined) =>
        (old ?? []).filter(
          (t) =>
            t.status !== "completed" &&
            t.status !== "failed" &&
            t.status !== "error",
        ),
      );
    },
  });
}
