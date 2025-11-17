import {
  useQuery,
  useQueryClient,
  type UseQueryOptions,
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

export const useGetFiltersSearchQuery = (
  search: string,
  limit = 20,
  options?: Omit<UseQueryOptions<KnowledgeFilter[]>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function getFilters(): Promise<KnowledgeFilter[]> {
    const response = await fetch("/api/knowledge-filter/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: search, limit }),
    });

    const json = await response.json();
    if (!response.ok || !json.success) {
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
