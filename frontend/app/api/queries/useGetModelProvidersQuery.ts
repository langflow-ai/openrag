import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface ModelProviderEntry {
  name: string;
  display_name: string;
}

export interface ModelProvidersResponse {
  run_mode: string;
  providers: ModelProviderEntry[];
}

/**
 * The providers this deployment offers, filtered by OPENRAG_RUN_MODE.
 *
 * `config/model_providers.yaml` on the backend is the only source of truth for
 * this list: Settings cards, the Onboarding tabs and the model pickers all
 * render what it returns, so the frontend keeps no denylist of its own and
 * brand/theme never decides whether a provider is available.
 */
export const useGetModelProvidersQuery = (
  options?: Omit<
    UseQueryOptions<ModelProvidersResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["models", "providers"] as const,
      queryFn: async (): Promise<ModelProvidersResponse> => {
        const response = await fetch("/api/models/providers");
        if (!response.ok) {
          throw new Error("Failed to fetch the model providers");
        }
        return (await response.json()) as ModelProvidersResponse;
      },
      // Run mode and the config file are fixed for the life of the process.
      staleTime: Number.POSITIVE_INFINITY,
      gcTime: Number.POSITIVE_INFINITY,
      refetchOnWindowFocus: false,
      ...options,
    },
    queryClient,
  );
};
