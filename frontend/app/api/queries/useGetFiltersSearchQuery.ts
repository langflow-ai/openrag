import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface KnowledgeFilter {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
  active_source_count?: number;
}

export const useGetFiltersSearchQuery = (
  search: string,
  limit = 20,
  options?: Omit<UseQueryOptions<KnowledgeFilter[]>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getFilters(): Promise<KnowledgeFilter[]> {
    const response = await apiClient.post<{
      success?: boolean;
      filters?: KnowledgeFilter[];
    }>("/knowledge-filter/search", { query: search, limit });
    const json = response.data;
    if (response.status < 200 || response.status >= 300 || !json.success) {
      // ensure we always return a KnowledgeFilter[] to satisfy the return type
      return [];
    }
    return (json.filters || []) as KnowledgeFilter[];
  }

  return useQuery<KnowledgeFilter[]>(
    {
      queryKey: ["knowledge-filters", search, limit],
      queryFn: getFilters,
      ...options,
    },
    queryClient,
  );
};
