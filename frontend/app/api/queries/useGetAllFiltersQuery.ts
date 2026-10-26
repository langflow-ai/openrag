import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { KnowledgeFilter } from "./useGetFiltersSearchQuery";

async function getAllFilters(): Promise<KnowledgeFilter[]> {
  const response = await apiClient.post<{
    success?: boolean;
    filters?: KnowledgeFilter[];
  }>("/knowledge-filter/search", { query: "", limit: 1000 });
  const json = response.data;
  if (response.status < 200 || response.status >= 300 || !json.success) {
    return [];
  }
  return (json.filters || []) as KnowledgeFilter[];
}

export const useGetAllFiltersQuery = (
  options?: Omit<UseQueryOptions<KnowledgeFilter[]>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  return useQuery<KnowledgeFilter[]>(
    {
      queryKey: ["knowledge-filters", "all"],
      queryFn: getAllFilters,
      ...options,
    },
    queryClient,
  );
};
