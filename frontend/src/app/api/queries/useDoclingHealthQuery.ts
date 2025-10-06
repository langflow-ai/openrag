import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface DoclingHealthResponse {
  status: "healthy" | "unhealthy";
  message?: string;
}

export const useDoclingHealthQuery = (
  options?: Omit<UseQueryOptions<DoclingHealthResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function checkDoclingHealth(): Promise<DoclingHealthResponse> {
    try {
      const response = await fetch("http://127.0.0.1:5001/health", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (response.ok) {
        return { status: "healthy" };
      } else {
        return {
          status: "unhealthy",
          message: `Health check failed with status: ${response.status}`,
        };
      }
    } catch (error) {
      return {
        status: "unhealthy",
        message: error instanceof Error ? error.message : "Connection failed",
      };
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["docling-health"],
      queryFn: checkDoclingHealth,
      retry: 1,
      refetchInterval: 30000, // Check every 30 seconds
      staleTime: 25000, // Consider data stale after 25 seconds
      ...options,
    },
    queryClient,
  );

  return queryResult;
};