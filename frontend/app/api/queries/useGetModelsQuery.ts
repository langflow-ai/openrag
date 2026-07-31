import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { formatProviderErrorMessage } from "@/lib/chat-stream-errors";
import { useGetSettingsQuery } from "./useGetSettingsQuery";

export interface ModelOption {
  value: string;
  label: string;
  default?: boolean;
  supports_images?: boolean;
}

export interface ModelsResponse {
  language_models: ModelOption[];
  embedding_models: ModelOption[];
}

export interface OpenAIModelsParams {
  apiKey?: string;
  /** When true, omit api_key so the backend uses configured/env credentials. */
  useEnvKey?: boolean;
}

export interface AnthropicModelsParams {
  apiKey?: string;
  /** When true, omit api_key so the backend uses configured/env credentials. */
  useEnvKey?: boolean;
}

export interface OllamaModelsParams {
  endpoint?: string;
}

export interface IBMModelsParams {
  endpoint?: string;
  apiKey?: string;
  projectId?: string;
  /** When true, omit api_key so the backend uses configured/env credentials. */
  useEnvKey?: boolean;
}

async function throwModelsFetchError(
  response: Response,
  fallback: string,
): Promise<never> {
  const data = await response.json().catch(() => ({}));
  const raw =
    data && typeof data === "object" && typeof data.error === "string"
      ? data.error
      : fallback;
  throw new Error(formatProviderErrorMessage(raw));
}

export const useGetOpenAIModelsQuery = (
  params?: OpenAIModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();
  const useEnvKey = !!params?.useEnvKey;
  const apiKey = useEnvKey ? "" : params?.apiKey || "";

  return useQuery(
    {
      queryKey: ["models", "openai", useEnvKey, apiKey] as const,
      queryFn: async (): Promise<ModelsResponse> => {
        const headers: Record<string, string> = {};
        if (!useEnvKey && apiKey) {
          headers["X-Api-Key"] = apiKey;
        }

        const response = await fetch("/api/models/openai", { headers });
        if (response.ok) {
          return (await response.json()) as ModelsResponse;
        }
        return throwModelsFetchError(response, "Failed to fetch OpenAI models");
      },
      staleTime: 0,
      gcTime: 0,
      retry: false,
      ...options,
    },
    queryClient,
  );
};

export const useGetAnthropicModelsQuery = (
  params?: AnthropicModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();
  const useEnvKey = !!params?.useEnvKey;
  const apiKey = useEnvKey ? "" : params?.apiKey || "";

  return useQuery(
    {
      queryKey: ["models", "anthropic", useEnvKey, apiKey] as const,
      queryFn: async (): Promise<ModelsResponse> => {
        const headers: Record<string, string> = {};
        if (!useEnvKey && apiKey) {
          headers["X-Api-Key"] = apiKey;
        }

        const response = await fetch("/api/models/anthropic", { headers });
        if (response.ok) {
          return (await response.json()) as ModelsResponse;
        }
        return throwModelsFetchError(
          response,
          "Failed to fetch Anthropic models",
        );
      },
      staleTime: 0,
      gcTime: 0,
      retry: false,
      ...options,
    },
    queryClient,
  );
};

export const useGetOllamaModelsQuery = (
  params?: OllamaModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();
  const endpoint = params?.endpoint || "";

  return useQuery(
    {
      queryKey: ["models", "ollama", endpoint] as const,
      queryFn: async (): Promise<ModelsResponse> => {
        const url = new URL("/api/models/ollama", window.location.origin);
        if (endpoint) {
          url.searchParams.set("endpoint", endpoint);
        }

        const response = await fetch(url.toString());
        if (response.ok) {
          return (await response.json()) as ModelsResponse;
        }
        return throwModelsFetchError(response, "Failed to fetch Ollama models");
      },
      staleTime: 0,
      gcTime: 0,
      retry: false,
      ...options,
    },
    queryClient,
  );
};

export const useGetIBMModelsQuery = (
  params?: IBMModelsParams,
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();
  const useEnvKey = !!params?.useEnvKey;
  const endpoint = params?.endpoint || "";
  const projectId = params?.projectId || "";
  const apiKey = useEnvKey ? "" : params?.apiKey || "";

  return useQuery(
    {
      queryKey: [
        "models",
        "ibm",
        useEnvKey,
        endpoint,
        projectId,
        apiKey,
      ] as const,
      queryFn: async (): Promise<ModelsResponse> => {
        const url = new URL("/api/models/ibm", window.location.origin);
        if (endpoint) {
          url.searchParams.set("endpoint", endpoint);
        }
        if (projectId) {
          url.searchParams.set("project_id", projectId);
        }

        const headers: Record<string, string> = {};
        if (!useEnvKey && apiKey) {
          headers["X-Api-Key"] = apiKey;
        }

        const response = await fetch(url.toString(), { headers });
        if (response.ok) {
          return (await response.json()) as ModelsResponse;
        }
        return throwModelsFetchError(response, "Failed to fetch IBM models");
      },
      staleTime: 0,
      gcTime: 0,
      retry: false,
      ...options,
    },
    queryClient,
  );
};

/**
 * Hook that automatically fetches models for the current LLM provider
 * based on the settings configuration
 */
export const useGetCurrentProviderModelsQuery = (
  options?: Omit<UseQueryOptions<ModelsResponse>, "queryKey" | "queryFn">,
) => {
  const { data: settings } = useGetSettingsQuery();
  const currentProvider = settings?.agent?.llm_provider;

  const openaiModels = useGetOpenAIModelsQuery(
    { useEnvKey: true },
    {
      enabled: currentProvider === "openai" && options?.enabled !== false,
      ...options,
    },
  );

  const anthropicModels = useGetAnthropicModelsQuery(
    { useEnvKey: true },
    {
      enabled: currentProvider === "anthropic" && options?.enabled !== false,
      ...options,
    },
  );

  const ollamaModels = useGetOllamaModelsQuery(
    { endpoint: settings?.providers?.ollama?.endpoint },
    {
      enabled:
        currentProvider === "ollama" &&
        !!settings?.providers?.ollama?.endpoint &&
        options?.enabled !== false,
      ...options,
    },
  );

  const ibmModels = useGetIBMModelsQuery(
    {
      endpoint: settings?.providers?.watsonx?.endpoint,
      projectId: settings?.providers?.watsonx?.project_id,
      useEnvKey: true,
    },
    {
      enabled:
        currentProvider === "watsonx" &&
        !!settings?.providers?.watsonx?.endpoint &&
        !!settings?.providers?.watsonx?.project_id &&
        options?.enabled !== false,
      ...options,
    },
  );

  switch (currentProvider) {
    case "openai":
      return openaiModels;
    case "anthropic":
      return anthropicModels;
    case "ollama":
      return ollamaModels;
    case "watsonx":
      return ibmModels;
    default:
      return openaiModels;
  }
};
