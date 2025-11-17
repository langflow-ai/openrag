import {
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

export interface FacetBucket {
  key: string;
  count: number;
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
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit, scoreThreshold }),
    });

    const json = await response.json().catch(() => ({}));

    if (!response.ok) {
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
