import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export type ComponentState = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ComponentBuild {
  git_sha?: string | null;
  build_time?: string | null;
  image?: string | null;
  image_digest?: string | null;
}

export interface ComponentStatus {
  name: string;
  display_name: string;
  status: ComponentState;
  required: boolean;
  latency_ms?: number | null;
  message?: string | null;
  version?: string | null;
  build?: ComponentBuild;
  metadata?: Record<string, unknown>;
  /** Non-null when the last health-check failed; used to gate the Logs button. */
  last_error?: string | null;
}

export interface ConsoleStatusResponse {
  overall_status: ComponentState;
  checked_at: string;
  components: ComponentStatus[];
}

async function fetchConsoleStatus(): Promise<ConsoleStatusResponse> {
  const response = await fetch("/api/status");
  if (!response.ok) {
    // Surface the real error (401 auth, 500 server, etc.) so the query
    // enters an error state instead of resolving to an empty components array.
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : typeof body?.error === "string"
          ? body.error
          : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return response.json() as Promise<ConsoleStatusResponse>;
}

export const useConsoleStatusQuery = (
  options?: Omit<
    UseQueryOptions<ConsoleStatusResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["console-status"],
      queryFn: fetchConsoleStatus,
      retry: 1,
      refetchInterval: 30000,
      // Re-check when the user returns to the tab so a status change that
      // happened while away surfaces promptly (drives the header notification).
      refetchOnWindowFocus: true,
      staleTime: 15000,
      ...options,
    },
    queryClient,
  );
};
