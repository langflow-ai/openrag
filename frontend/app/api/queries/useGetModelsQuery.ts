import {
  type QueryClient,
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { CatalogModel } from "@/components/models/catalog-models";
import { apiClient } from "@/lib/api-client";
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
  response: { data?: unknown },
  fallback: string,
): Promise<never> {
  const data = response.data ?? {};
  const raw =
    data &&
    typeof data === "object" &&
    "error" in data &&
    typeof data.error === "string"
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

        const response = await apiClient.post<ModelsResponse>(
          "/models/openai",
          body,
        );
        if (response.status >= 200 && response.status < 300) {
          return response.data;
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

        const response = await apiClient.post<ModelsResponse>(
          "/models/anthropic",
          body,
        );
        if (response.status >= 200 && response.status < 300) {
          return response.data;
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
        const path = endpoint
          ? `/models/ollama?endpoint=${encodeURIComponent(endpoint)}`
          : "/models/ollama";
        const response = await apiClient.get<ModelsResponse>(path);
        if (response.status >= 200 && response.status < 300) {
          return response.data;
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

        const response = await apiClient.post<ModelsResponse>(
          "/models/ibm",
          body,
        );
        if (response.status >= 200 && response.status < 300) {
          return response.data;
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
  /**
   * Whether `POST /api/models/{key}/discover` can list what this provider
   * serves from credentials that are not saved yet (cluster-hosted providers).
   */
  discovers_models?: boolean;
}

export interface ModelCatalogResponse {
  providers: CatalogProvider[];
}

const MODEL_CATALOG_QUERY_FILTERS = {
  queryKey: ["models", "catalog"],
  exact: true,
} as const;

/**
 * Refetch the catalogue after a save that can change it — a cluster-hosted
 * provider is listed with its *saved* credentials. Fire-and-forget, so the
 * caller's mutation never waits on a slow cluster listing.
 *
 * Cancelling first matters: while the catalogue's first load is in flight
 * (no data yet), invalidateQueries joins that pre-save request instead of
 * starting a new one, and staleTime: Infinity would then keep its result for
 * the tab's lifetime. Cancelling reverts the query to its pre-fetch state, so
 * the invalidation is guaranteed a post-save fetch.
 */
export const refreshModelCatalog = (queryClient: QueryClient): void => {
  void queryClient
    .cancelQueries(MODEL_CATALOG_QUERY_FILTERS)
    .then(() => queryClient.invalidateQueries(MODEL_CATALOG_QUERY_FILTERS))
    .catch((error: unknown) => {
      // Both calls swallow fetch errors themselves; this guards the chain.
      console.warn(
        `Failed to refresh the model catalogue after saving. Error: ${error}.`,
      );
    });
};

/**
 * LiteLLM's bundled model list, grouped by provider. Static for the tab's
 * lifetime — same as openrag-next's `/agent/model-catalog` fetch — except
 * where a save refreshes it through `refreshModelCatalog`.
 */
export const useGetModelCatalogQuery = (
  options?: Omit<UseQueryOptions<ModelCatalogResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: MODEL_CATALOG_QUERY_FILTERS.queryKey,
      queryFn: async (): Promise<ModelCatalogResponse> => {
        const response =
          await apiClient.get<ModelCatalogResponse>("/models/catalog");
        if (response.status >= 200 && response.status < 300) {
          return response.data;
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
