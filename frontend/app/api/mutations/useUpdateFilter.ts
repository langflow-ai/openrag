import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { KnowledgeFilter } from "../queries/useGetFiltersSearchQuery";

export interface UpdateFilterRequest {
  id: string;
  name?: string;
  description?: string;
  queryData?: string; // stringified ParsedQueryData
}

export interface UpdateFilterResponse {
  success: boolean;
  filter: KnowledgeFilter;
  message?: string;
}

async function updateFilter(
  data: UpdateFilterRequest,
): Promise<UpdateFilterResponse> {
  // Build a body with only provided fields
  const body: Record<string, unknown> = {};
  if (typeof data.name !== "undefined") body.name = data.name;
  if (typeof data.description !== "undefined")
    body.description = data.description;
  if (typeof data.queryData !== "undefined") body.queryData = data.queryData;

  const response = await apiClient.put<UpdateFilterResponse>(
    `/knowledge-filter/${data.id}`,
    body,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorMessage =
      (response.data as { error?: string }).error ||
      "Failed to update knowledge filter";
    throw new Error(errorMessage);
  }

  return response.data;
}

export const useUpdateFilter = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateFilter,
    onSuccess: () => {
      // Refresh any knowledge filter lists/searches
      queryClient.invalidateQueries({ queryKey: ["knowledge-filters"] });
    },
  });
};
