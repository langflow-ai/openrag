import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useGetSettingsQuery } from "./useGetSettingsQuery";

export interface ProviderHealthDetails {
  llm_model: string;
  embedding_model: string;
  endpoint?: string | null;
}

export interface ProviderHealthResponse {
  status: "healthy" | "unhealthy" | "error" | "backend-unavailable";
  message: string;
  provider?: string;
  llm_provider?: string;
  embedding_provider?: string;
  llm_error?: string | null;
  embedding_error?: string | null;
  details?: ProviderHealthDetails;
}

export interface ProviderHealthParams {
  provider?: "openai" | "ollama" | "watsonx";
}

// Track consecutive failures for exponential backoff
const failureCountMap = new Map<string, number>();

export const useProviderHealthQuery = (
  params?: ProviderHealthParams,
  options?: Omit<
    UseQueryOptions<ProviderHealthResponse, Error>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  const { data: settings = {} } = useGetSettingsQuery();

  async function checkProviderHealth(): Promise<ProviderHealthResponse> {
    try {
      const url = new URL("/api/provider/health", window.location.origin);

      // Add provider query param if specified
      if (params?.provider) {
        url.searchParams.set("provider", params.provider);
      }

      const response = await fetch(url.toString());

      if (response.ok) {
        return await response.json();
      } else if (response.status === 503) {
        // Backend is up but provider validation failed
        const errorData = await response.json().catch(() => ({}));
        return {
          status: "unhealthy",
          message: errorData.message || "Provider validation failed",
          provider: errorData.provider || params?.provider || "unknown",
          llm_provider: errorData.llm_provider,
          embedding_provider: errorData.embedding_provider,
          llm_error: errorData.llm_error,
          embedding_error: errorData.embedding_error,
          details: errorData.details,
        };
      } else {
        // Other backend errors (400, etc.) - treat as provider issues
        const errorData = await response.json().catch(() => ({}));
        return {
          status: "error",
          message: errorData.message || "Failed to check provider health",
          provider: errorData.provider || params?.provider || "unknown",
          llm_provider: errorData.llm_provider,
          embedding_provider: errorData.embedding_provider,
          llm_error: errorData.llm_error,
          embedding_error: errorData.embedding_error,
          details: errorData.details,
        };
      }
    } catch (error) {
      // Network error - backend is likely down, don't show provider banner
      return {
        status: "backend-unavailable",
        message: error instanceof Error ? error.message : "Connection failed",
        provider: params?.provider || "unknown",
      };
    }
  }

  const queryKey = ["provider", "health"];
  const failureCountKey = queryKey.join("-");

  const queryResult = useQuery(
    {
      queryKey,
      queryFn: checkProviderHealth,
      retry: false, // Don't retry health checks automatically
      refetchInterval: (query) => {
        const data = query.state.data;
        const status = data?.status;
        
        // If healthy, reset failure count and check every 30 seconds
        if (status === "healthy") {
          failureCountMap.set(failureCountKey, 0);
          return 30000;
        }
        
        // If backend unavailable, use moderate polling
        if (status === "backend-unavailable") {
          return 15000;
        }
        
        // For unhealthy/error status, use exponential backoff
        const currentFailures = failureCountMap.get(failureCountKey) || 0;
        failureCountMap.set(failureCountKey, currentFailures + 1);
        
        // Exponential backoff: 5s, 10s, 20s, then 30s
        const backoffDelays = [5000, 10000, 20000, 30000];
        const delay = backoffDelays[Math.min(currentFailures, backoffDelays.length - 1)];
        
        return delay;
      },
      refetchOnWindowFocus: false, // Disabled to reduce unnecessary calls on tab switches
      refetchOnMount: true,
      staleTime: 30000, // Consider data stale after 30 seconds
      enabled: !!settings?.edited && options?.enabled !== false, // Only run after onboarding is complete
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
