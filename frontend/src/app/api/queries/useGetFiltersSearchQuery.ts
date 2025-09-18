import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface KnowledgeFilter {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
}

export interface FiltersSearchResponse {
  success: boolean;
  filters: KnowledgeFilter[];
  error?: string;
}

export const useGetFiltersSearchQuery = (
  search: string,
  limit = 20,
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">
) => {
  const queryClient = useQueryClient();

  async function getFilters(): Promise<KnowledgeFilter[]> {
    try {
      const response = await fetch("/api/knowledge-filter/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: search, limit }),
      });

      const result: FiltersSearchResponse = await response.json();
      if (response.ok && result.success) {
        return result.filters || [];
      }
      console.error("Failed to load knowledge filters:", result.error);
      return [];
    } catch (error) {
      console.error("Error loading knowledge filters:", error);
      return [];
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["knowledge-filters", search, limit],
      placeholderData: (prev) => prev,
      queryFn: getFilters,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
