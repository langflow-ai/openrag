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

export interface OllamaModelsParams {
  endpoint?: string;
}

export interface IBMModelsParams {
  api_key?: string;
  endpoint?: string;
  project_id?: string;
}

export const useGetOpenAIModelsQuery = (
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getOpenAIModels(): Promise<ModelsResponse> {
    const response = await fetch("/api/models/openai");
    if (response.ok) {
      return await response.json();
    } else {
      throw new Error("Failed to fetch OpenAI models");
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["models", "openai"],
      queryFn: getOpenAIModels,
      staleTime: 5 * 60 * 1000, // 5 minutes
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
      staleTime: 5 * 60 * 1000, // 5 minutes
      enabled: !!params?.endpoint, // Only run if endpoint is provided
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
    const url = "/api/models/ibm";

    // If we have credentials, use POST to send them securely
    if (params?.api_key || params?.endpoint || params?.project_id) {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          api_key: params.api_key,
          endpoint: params.endpoint,
          project_id: params.project_id,
        }),
      });

      if (response.ok) {
        return await response.json();
      } else {
        throw new Error("Failed to fetch IBM models");
      }
    } else {
      // Use GET for default models
      const response = await fetch(url);
      if (response.ok) {
        return await response.json();
      } else {
        throw new Error("Failed to fetch IBM models");
      }
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["models", "ibm", params],
      queryFn: getIBMModels,
      staleTime: 5 * 60 * 1000, // 5 minutes
      enabled: !!(params?.api_key && params?.endpoint && params?.project_id), // Only run if all credentials are provided
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
