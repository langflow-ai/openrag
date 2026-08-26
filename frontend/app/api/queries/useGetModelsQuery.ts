import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { CatalogModel } from "@/app/settings/_helpers/catalog-models";
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
  /** Optional override to list models from a self-hosted OpenAI-compatible gateway. */
  baseUrl?: string;
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
  const baseUrl = params?.baseUrl || "";

  return useQuery(
    {
      queryKey: ["models", "openai", useEnvKey, apiKey, baseUrl] as const,
      queryFn: async (): Promise<ModelsResponse> => {
        const body: { api_key?: string; base_url?: string } = {};
        if (!useEnvKey && apiKey) {
          body.api_key = apiKey;
        }
        if (baseUrl) {
          body.base_url = baseUrl;
        }

        const response = await fetch("/api/models/openai", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
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
        const body: { api_key?: string } = {};
        if (!useEnvKey && apiKey) {
          body.api_key = apiKey;
        }

        const response = await fetch("/api/models/anthropic", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
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
        const body: {
          endpoint?: string;
          api_key?: string;
          project_id?: string;
        } = {};
        if (endpoint) {
          body.endpoint = endpoint;
        }
        if (projectId) {
          body.project_id = projectId;
        }
        if (!useEnvKey && apiKey) {
          body.api_key = apiKey;
        }

        const response = await fetch("/api/models/ibm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
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
    { useEnvKey: true, baseUrl: settings?.providers?.openai?.base_url },
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

export interface CatalogCredentialField {
  key: string;
  label: string;
  placeholder?: string | null;
  tooltip?: string | null;
  required: boolean;
  field_type: string;
  options?: unknown;
  default_value?: unknown;
}

export interface CatalogProvider {
  key: string;
  name: string;
  credential_fields: CatalogCredentialField[];
  model_placeholder: string | null;
  models: CatalogModel[];
  embedding_models: CatalogModel[];
}

export interface ModelCatalogResponse {
  providers: CatalogProvider[];
}

/**
 * LiteLLM's bundled model list, grouped by provider. Static for the tab's
 * lifetime — same as openrag-next's `/agent/model-catalog` fetch.
 */
export const useGetModelCatalogQuery = (
  options?: Omit<UseQueryOptions<ModelCatalogResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["models", "catalog"] as const,
      queryFn: async (): Promise<ModelCatalogResponse> => {
        const response = await fetch("/api/models/catalog");
        if (response.ok) {
          return (await response.json()) as ModelCatalogResponse;
        }
        return throwModelsFetchError(
          response,
          "Failed to fetch the model catalogue",
        );
      },
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      retry: false,
      ...options,
    },
    queryClient,
  );
};
