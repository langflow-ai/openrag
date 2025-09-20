import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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
      retry: 2,
      enabled: !!params?.apiKey, // Only run if API key is provided
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
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
      retry: 2,
      enabled: !!params?.endpoint, // Only run if endpoint is provided
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
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
      retry: 2,
      enabled: !!params?.endpoint && !!params?.apiKey && !!params?.projectId, // Only run if all required params are provided
      staleTime: 0, // Always fetch fresh data
      gcTime: 0, // Don't cache results
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
