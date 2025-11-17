import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KnowledgeFilter } from "../queries/useGetFiltersSearchQuery";

export interface CreateFilterRequest {
  name: string;
  description?: string;
  queryData: string; // stringified ParsedQueryData
}

export interface CreateFilterResponse {
  success: boolean;
  filter: KnowledgeFilter;
  message?: string;
}

async function createFilter(
  data: CreateFilterRequest,
): Promise<CreateFilterResponse> {
  const response = await fetch("/api/knowledge-filter", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: data.name,
      description: data.description ?? "",
      queryData: data.queryData,
    }),
  });

  const json = await response.json().catch(() => ({}));

  if (!response.ok) {
    const errorMessage =
      (json && (json.error as string)) || "Failed to create knowledge filter";
    throw new Error(errorMessage);
  }

  return json as CreateFilterResponse;
}

export const useCreateFilter = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createFilter,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge-filters"] });
    },
  });
};
