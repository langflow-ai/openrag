import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { getApiError } from "@/lib/status-utils";

export interface LogEntry {
  timestamp: string; // ISO-8601 UTC
  level: string; // "debug" | "info" | "warning" | "error" | "critical"
  message: string;
  detail?: string | null;
}

export interface ComponentLogsResponse {
  component: string;
  entries: LogEntry[];
  count: number;
}

async function fetchComponentLogs(
  component: string,
  tail = 100,
  signal?: AbortSignal,
): Promise<ComponentLogsResponse> {
  const response = await apiClient.get<ComponentLogsResponse>(
    `/status/${encodeURIComponent(component)}/logs?tail=${tail}`,
    { signal },
  );
  if (response.status < 200 || response.status >= 300) {
    const body = response.data ?? {};
    throw new Error(getApiError(body, response.status));
  }
  return response.data;
}

export const useComponentLogsQuery = (
  component: string | null,
  tail = 100,
  options?: Omit<
    UseQueryOptions<ComponentLogsResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  return useQuery({
    queryKey: ["component-logs", component, tail],
    queryFn: ({ signal }) =>
      fetchComponentLogs(component as string, tail, signal),
    enabled: !!component,
    retry: 1,
    staleTime: 5000,
    refetchOnWindowFocus: false,
    ...options,
  });
};
