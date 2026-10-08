import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { DiscoveredCatalogModels } from "@/components/models/catalog-models";

export type DiscoveredModels = DiscoveredCatalogModels;

export interface DiscoverProviderModelsParams {
  provider: string;
  credentials: Record<string, string>;
  authMethod?: string;
}

/**
 * Lists the models a cluster-hosted provider serves, using credentials typed
 * into a form that has not been saved yet.
 *
 * The catalogue only lists a cluster with *saved* credentials, so during
 * onboarding it can offer nothing but the configured fallback. A vLLM
 * `--served-model-name` can be anything, so the cluster is the only source
 * that knows what to offer.
 *
 * Deliberately not under the `["models"]` key: onboarding disables Submit
 * while anything there is fetching, and a slow cluster must not block it.
 */
export const useDiscoverProviderModelsQuery = (
  params: DiscoverProviderModelsParams,
  options?: Omit<UseQueryOptions<DiscoveredModels>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();
  const { provider, credentials, authMethod } = params;

  return useQuery(
    {
      queryKey: [
        "provider-model-discovery",
        provider,
        credentials,
        authMethod ?? null,
      ] as const,
      queryFn: async ({ signal }): Promise<DiscoveredModels> => {
        const response = await fetch(
          `/api/models/${encodeURIComponent(provider)}/discover`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              credentials,
              ...(authMethod ? { auth_method: authMethod } : {}),
            }),
            signal,
          },
        );
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(
            typeof data?.error === "string"
              ? data.error
              : "Unable to list models from the provider.",
          );
        }
        return {
          models: Array.isArray(data?.models) ? data.models : null,
          embedding_models: Array.isArray(data?.embedding_models)
            ? data.embedding_models
            : null,
        };
      },
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 5 * 60 * 1000,
      // The credentials are part of the key; don't keep them around longer
      // than the form that typed them.
      gcTime: 60 * 1000,
      ...options,
    },
    queryClient,
  );
};
