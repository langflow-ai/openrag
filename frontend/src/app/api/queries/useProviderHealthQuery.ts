import { ModelProvider } from "@/app/settings/helpers/model-helpers";
import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface ProviderHealthDetails {
  llm_model: string;
  embedding_model: string;
  endpoint?: string | null;
}

export interface ProviderHealthResponse {
  status: "healthy" | "unhealthy" | "error" | "backend-unavailable";
  message: string;
  provider: string;
  details?: ProviderHealthDetails;
}

export interface ProviderHealthParams {
  provider?: "openai" | "ollama" | "watsonx";
}

const providerTitleMap: Record<ModelProvider, string> = {
  openai: "OpenAI",
  ollama: "Ollama",
  watsonx: "IBM watsonx.ai",
};

export const useProviderHealthQuery = (
  params?: ProviderHealthParams,
  options?: Omit<
    UseQueryOptions<ProviderHealthResponse, Error>,
    "queryKey" | "queryFn"
  >
) => {
  const queryClient = useQueryClient();

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
          details: errorData.details,
        };
      } else {
        // Other backend errors (400, etc.) - treat as provider issues
        const errorData = await response.json().catch(() => ({}));
        return {
          status: "error",
          message: errorData.message || "Failed to check provider health",
          provider: errorData.provider || params?.provider || "unknown",
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
      ...options,
    },
    queryClient
  );

  return queryResult;
};

