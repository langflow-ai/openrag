import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface TaskStatus {
  task_id: string;
  status:
    | "pending"
    | "running"
    | "processing"
    | "completed"
    | "failed"
    | "error";
  total_files?: number;
  processed_files?: number;
  successful_files?: number;
  failed_files?: number;
  running_files?: number;
  pending_files?: number;
  created_at: string;
  updated_at: string;
  duration_seconds?: number;
  result?: Record<string, unknown>;
  error?: string;
  files?: Record<string, Record<string, unknown>>;
}

export const useGetTaskStatusQuery = (
  taskId: string,
  options?: Omit<UseQueryOptions<TaskStatus | null>, "queryKey" | "queryFn">
) => {
  const queryClient = useQueryClient();

  async function getTaskStatus(): Promise<TaskStatus | null> {
    if (!taskId) {
      return null;
    }

    const response = await fetch(`/api/tasks/${taskId}`);
    
    if (!response.ok) {
      if (response.status === 404) {
        return null; // Task not found
      }
      throw new Error("Failed to fetch task status");
    }

    return response.json();
  }

  const queryResult = useQuery(
    {
      queryKey: ["task-status", taskId],
      queryFn: getTaskStatus,
      refetchInterval: (data) => {
        // Only poll if the task is still active
        if (!data) {
          return false; // Stop polling if no data
        }

        const isActive = 
          data.status === "pending" || 
          data.status === "running" || 
          data.status === "processing";

        return isActive ? 3000 : false; // Poll every 3 seconds if active
      },
      refetchIntervalInBackground: true,
      staleTime: 0, // Always consider data stale to ensure fresh updates
      gcTime: 5 * 60 * 1000, // Keep in cache for 5 minutes
      enabled: !!taskId, // Only run if taskId is provided
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
