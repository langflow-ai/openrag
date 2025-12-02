import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface DoclingHealthResponse {
  status: "healthy" | "unhealthy" | "backend-unavailable";
  message?: string;
}

export const useDoclingHealthQuery = (
  options?: Omit<
    UseQueryOptions<DoclingHealthResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function checkDoclingHealth(): Promise<DoclingHealthResponse> {
    try {
      // Call backend proxy endpoint instead of direct localhost
      const response = await fetch("/api/docling/health", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        return { status: "healthy" };
      } else if (response.status === 503) {
        // Backend is up but docling is down (backend returns 503 for docling issues)
        return {
          status: "unhealthy",
          message: `Health check failed with status: ${response.status}`,
        };
      } else {
        // Other backend errors - treat as docling unhealthy
        return {
          status: "unhealthy",
          message: `Health check failed with status: ${response.status}`,
        };
      }
    } catch (error) {
      // Network error - backend is likely down, don't show docling banner
      return {
        status: "backend-unavailable",
        message: error instanceof Error ? error.message : "Connection failed",
      };
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["docling-health"],
      queryFn: checkDoclingHealth,
      retry: 1,
      refetchInterval: (query) => {
        // If healthy, check every 30 seconds; otherwise check every 3 seconds
        return query.state.data?.status === "healthy" ? 30000 : 3000;
      },
      refetchOnWindowFocus: false, // Disabled to reduce unnecessary calls on tab switches
      refetchOnMount: true,
      staleTime: 30000, // Consider data fresh for 30 seconds
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
