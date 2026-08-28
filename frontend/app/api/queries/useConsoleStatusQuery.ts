import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { getApiError } from "@/lib/status-utils";

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
  /** ISO-8601 UTC of when this component was last checked (drives "Last Sync"). */
  checked_at?: string | null;
}

export interface ConsoleStatusResponse {
  overall_status: ComponentState;
  checked_at: string;
  components: ComponentStatus[];
}

async function fetchConsoleStatus(): Promise<ConsoleStatusResponse> {
  const response = await fetch("/api/status");
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(getApiError(body, response.status));
  }
  return response.json() as Promise<ConsoleStatusResponse>;
}

export const useConsoleStatusQuery = (
  options?: Omit<
    UseQueryOptions<ConsoleStatusResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  return useQuery({
    queryKey: ["console-status"],
    queryFn: fetchConsoleStatus,
    retry: 1,
    refetchInterval: 30000,
    // Re-check when the user returns to the tab so a status change that
    // happened while away surfaces promptly (drives the header notification).
    refetchOnWindowFocus: true,
    staleTime: 15000,
    ...options,
  });
};
