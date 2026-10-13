import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface FacetBucket {
  key: string;
  label?: string;
  count?: number;
  doc_count?: number;
}

export interface SearchAggregations {
  data_sources?: { buckets: FacetBucket[] };
  document_types?: { buckets: FacetBucket[] };
  owners?: { buckets: FacetBucket[] };
  connector_types?: { buckets: FacetBucket[] };
}

type Options = Omit<
  UseQueryOptions<SearchAggregations>,
  "queryKey" | "queryFn"
>;

export const useGetSearchAggregations = (
  query: string,
  limit: number,
  scoreThreshold: number,
  options?: Options,
) => {
  const queryClient = useQueryClient();

  async function fetchAggregations(): Promise<SearchAggregations> {
    const response = await apiClient.post<{
      aggregations?: SearchAggregations;
      error?: string;
    }>("/search", { query, limit, scoreThreshold });
    const json = response.data;

    if (response.status < 200 || response.status >= 300) {
      throw new Error(
        (json && json.error) || "Failed to load search aggregations",
      );
    }

    return (json.aggregations || {}) as SearchAggregations;
  }

  return useQuery<SearchAggregations>(
    {
      queryKey: ["search-aggregations", query, limit, scoreThreshold],
      queryFn: fetchAggregations,
      placeholderData: (prev) => prev,
      ...options,
    },
    queryClient,
  );
};
