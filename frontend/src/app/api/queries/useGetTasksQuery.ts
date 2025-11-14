import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface TaskFileEntry {
  status?:
    | "pending"
    | "running"
    | "processing"
    | "completed"
    | "failed"
    | "error";
  result?: unknown;
  error?: string;
  retry_count?: number;
  created_at?: string;
  updated_at?: string;
  duration_seconds?: number;
  filename?: string;
  embedding_model?: string;
  embedding_dimensions?: number;
  [key: string]: unknown;
}

export interface Task {
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
  files?: Record<string, TaskFileEntry>;
}

export interface TasksResponse {
  tasks: Task[];
}

export const useGetTasksQuery = (
  options?: Omit<UseQueryOptions<Task[]>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getTasks(): Promise<Task[]> {
    const response = await fetch("/api/tasks");

    if (!response.ok) {
      throw new Error("Failed to fetch tasks");
    }

    const data: TasksResponse = await response.json();
    return data.tasks || [];
  }

  const queryResult = useQuery(
    {
      queryKey: ["tasks"],
      queryFn: getTasks,
      refetchInterval: (query) => {
        // Only poll if there are tasks with pending or running status
        const data = query.state.data;
        if (!data || data.length === 0) {
          return false; // Stop polling if no tasks
        }

        const hasActiveTasks = data.some(
          (task: Task) =>
            task.status === "pending" ||
            task.status === "running" ||
            task.status === "processing",
        );

        return hasActiveTasks ? 3000 : false; // Poll every 3 seconds if active tasks exist
      },
      refetchIntervalInBackground: true,
      staleTime: 0, // Always consider data stale to ensure fresh updates
      gcTime: 5 * 60 * 1000, // Keep in cache for 5 minutes
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
