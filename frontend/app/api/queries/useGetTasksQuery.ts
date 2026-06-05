import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

/** Component that failed, from GET /tasks/enhanced file metadata. */
export type TaskFailureComponent =
  | "docling"
  | "openrag"
  | "langflow"
  | "opensearch";

/** Pipeline or validation step where failure occurred. */
export type TaskFailurePhase =
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "file_validation"
  | "cancelled"
  | "unknown";

/** Who can resolve the failure (enhanced API). */
export type TaskActionableBy = "USER_ACTIONABLE" | "RETRYABLE";

export interface TaskFileEntry {
  status?:
    | "pending"
    | "running"
    | "processing"
    | "completed"
    | "skipped"
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
  phase?: "docling" | "langflow" | "complete" | string;
  docling_status?: string;
  docling_task_id?: string;
  /** Present on failed files when the enhanced API can classify the failure. */
  component?: TaskFailureComponent;
  failure_phase?: TaskFailurePhase;
  user_facing_message?: string;
  actionable_by?: TaskActionableBy;
}

export interface Task {
  task_id: string;
  status:
    | "pending"
    | "running"
    | "processing"
    | "completed"
    | "skipped"
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

export const TASKS_QUERY_KEY = ["tasks", "enhanced"] as const;

export const useGetTasksQuery = (
  options?: Omit<UseQueryOptions<Task[]>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getTasks(): Promise<Task[]> {
    const response = await fetch("/api/tasks/enhanced");

    if (!response.ok) {
      throw new Error("Failed to fetch tasks");
    }

    const data: TasksResponse = await response.json();
    return data.tasks || [];
  }

  const queryResult = useQuery(
    {
      queryKey: [...TASKS_QUERY_KEY],
      queryFn: getTasks,
      refetchInterval: (query) => {
        const data = query.state.data;
        if (!data || data.length === 0) {
          return false;
        }

        const hasActiveTasks = data.some(
          (task: Task) =>
            task.status === "pending" ||
            task.status === "running" ||
            task.status === "processing",
        );

        return hasActiveTasks ? 3000 : false;
      },
      refetchIntervalInBackground: true,
      staleTime: 0,
      gcTime: 5 * 60 * 1000,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
