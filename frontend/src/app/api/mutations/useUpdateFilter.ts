import { useMutation, useQueryClient } from "@tanstack/react-query";
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

  const response = await fetch(`/api/knowledge-filter/${data.id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const json = await response.json().catch(() => ({}));

  if (!response.ok) {
    const errorMessage =
      (json && (json.error as string)) || "Failed to update knowledge filter";
    throw new Error(errorMessage);
  }

  return json as UpdateFilterResponse;
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
