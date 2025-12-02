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

  const queryResult = useQuery(
    {
      queryKey: ["provider", "health"],
      queryFn: checkProviderHealth,
      retry: false, // Don't retry health checks automatically
      refetchInterval: (query) => {
        // If healthy, check every 30 seconds; otherwise check every 3 seconds
        return query.state.data?.status === "healthy" ? 30000 : 3000;
      },
      refetchOnWindowFocus: false, // Disabled to reduce unnecessary calls on tab switches
      refetchOnMount: true,
      staleTime: 30000, // Consider data fresh for 30 seconds
      enabled: !!settings?.edited && options?.enabled !== false, // Only run after onboarding is complete
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
