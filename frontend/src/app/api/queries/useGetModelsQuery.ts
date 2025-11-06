import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useGetSettingsQuery } from "./useGetSettingsQuery";

export interface ModelOption {
  value: string;
  label: string;
  default?: boolean;
}

export interface ModelsResponse {
  language_models: ModelOption[];
  embedding_models: ModelOption[];
}

export interface OpenAIModelsParams {
  apiKey?: string;
}

export interface OllamaModelsParams {
  endpoint?: string;
}

export interface IBMModelsParams {
  endpoint?: string;
  apiKey?: string;
  projectId?: string;
}

export const useGetOpenAIModelsQuery = (
  params?: OpenAIModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getOpenAIModels(): Promise<ModelsResponse> {
    const url = new URL("/api/models/openai", window.location.origin);
    if (params?.apiKey) {
      url.searchParams.set("api_key", params.apiKey);
    }

    const response = await fetch(url.toString());
    if (response.ok) {
      return await response.json();
    } else {
      throw new Error("Failed to fetch OpenAI models");
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["models", "openai", params],
      queryFn: getOpenAIModels,
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
      retry: false,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};

export const useGetOllamaModelsQuery = (
  params?: OllamaModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getOllamaModels(): Promise<ModelsResponse> {
    const url = new URL("/api/models/ollama", window.location.origin);
    if (params?.endpoint) {
      url.searchParams.set("endpoint", params.endpoint);
    }

    const response = await fetch(url.toString());
    if (response.ok) {
      return await response.json();
    } else {
      throw new Error("Failed to fetch Ollama models");
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["models", "ollama", params],
      queryFn: getOllamaModels,
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
      retry: false,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};

export const useGetIBMModelsQuery = (
  params?: IBMModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getIBMModels(): Promise<ModelsResponse> {
    const url = new URL("/api/models/ibm", window.location.origin);
    if (params?.endpoint) {
      url.searchParams.set("endpoint", params.endpoint);
    }
    if (params?.apiKey) {
      url.searchParams.set("api_key", params.apiKey);
    }
    if (params?.projectId) {
      url.searchParams.set("project_id", params.projectId);
    }

    const response = await fetch(url.toString());
    if (response.ok) {
      return await response.json();
    } else {
      throw new Error("Failed to fetch IBM models");
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["models", "ibm", params],
      queryFn: getIBMModels,
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
      retry: false,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};

/**
 * Hook that automatically fetches models for the current provider
 * based on the settings configuration
 */
export const useGetCurrentProviderModelsQuery = (
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const { data: settings } = useGetSettingsQuery();
  const currentProvider = settings?.provider?.model_provider;

  // Determine which hook to use based on current provider
  const openaiModels = useGetOpenAIModelsQuery(
    { apiKey: "" },
    {
      enabled: currentProvider === "openai" && options?.enabled !== false,
      ...options,
    }
  );

  const ollamaModels = useGetOllamaModelsQuery(
    { endpoint: settings?.provider?.endpoint },
    {
      enabled: currentProvider === "ollama" && !!settings?.provider?.endpoint && options?.enabled !== false,
      ...options,
    }
  );

  const ibmModels = useGetIBMModelsQuery(
    {
      endpoint: settings?.provider?.endpoint,
      apiKey: "",
      projectId: settings?.provider?.project_id,
    },
    {
      enabled:
        currentProvider === "watsonx" &&
        !!settings?.provider?.endpoint &&
        !!settings?.provider?.project_id &&
        options?.enabled !== false,
      ...options,
    }
  );

  // Return the appropriate query result based on current provider
  switch (currentProvider) {
    case "openai":
      return openaiModels;
    case "ollama":
      return ollamaModels;
    case "watsonx":
      return ibmModels;
    default:
      // Return a default/disabled query if no provider is set
      return {
        data: undefined,
        isLoading: false,
        error: null,
        refetch: async () => ({ data: undefined }),
      } as ReturnType<typeof useGetOpenAIModelsQuery>;
  }
};
