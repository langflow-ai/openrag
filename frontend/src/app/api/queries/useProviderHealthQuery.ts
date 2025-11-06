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
  status: "healthy" | "unhealthy" | "error";
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
    const url = new URL("/api/provider/health", window.location.origin);
    
    // Add provider query param if specified
    if (params?.provider) {
      url.searchParams.set("provider", params.provider);
    }

    const response = await fetch(url.toString());
    
    if (response.ok) {
      return await response.json();
    } else {
      // For 400 and 503 errors, still parse JSON for error details
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`${providerTitleMap[errorData.provider as ModelProvider] || "Provider"} error: ${errorData.message || "Failed to check provider health"}`);
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

