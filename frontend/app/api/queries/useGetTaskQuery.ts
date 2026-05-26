import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import type { Task } from "@/app/api/queries/useGetTasksQuery";

export function useGetTaskQuery(
  taskId: string | null,
  options?: Omit<UseQueryOptions<Task | null>, "queryKey" | "queryFn">,
) {
  return useQuery({
    queryKey: ["tasks", taskId],
    queryFn: async (): Promise<Task | null> => {
      if (!taskId) {
        return null;
      }
      //will be replace /api/tasks/{taskId}/enhanced, when backend merged
      const response = await fetch(`/api/tasks/${taskId}`);
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new Error("Failed to fetch task");
      }
      return response.json() as Promise<Task>;
    },
    enabled: !!taskId,
    ...options,
  });
}
