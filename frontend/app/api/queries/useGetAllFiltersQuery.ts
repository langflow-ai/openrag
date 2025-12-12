import {
	type UseQueryOptions,
	useQuery,
	useQueryClient,
} from "@tanstack/react-query";
import type { KnowledgeFilter } from "./useGetFiltersSearchQuery";

export const useGetAllFiltersQuery = (
	options?: Omit<UseQueryOptions<KnowledgeFilter[]>, "queryKey" | "queryFn">,
) => {
	const queryClient = useQueryClient();

	async function getAllFilters(): Promise<KnowledgeFilter[]> {
		const response = await fetch("/api/knowledge-filter/search", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ query: "", limit: 1000 }), // Fetch all filters
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
			queryKey: ["knowledge-filters", "all"],
			queryFn: getAllFilters,
			...options,
		},
		queryClient,
	);
};
