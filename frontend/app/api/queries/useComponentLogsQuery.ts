import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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
): Promise<ComponentLogsResponse> {
  const response = await fetch(
    `/api/status/${encodeURIComponent(component)}/logs?tail=${tail}`,
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return response.json() as Promise<ComponentLogsResponse>;
}

export const useComponentLogsQuery = (
  component: string | null,
  tail = 100,
  options?: Omit<
    UseQueryOptions<ComponentLogsResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["component-logs", component, tail],
      queryFn: () => fetchComponentLogs(component as string, tail),
      enabled: !!component,
      retry: 1,
      staleTime: 5000,
      refetchOnWindowFocus: false,
      ...options,
    },
    queryClient,
  );
};
