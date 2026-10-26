import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
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
  const response = await apiClient.post<CreateFilterResponse>(
    "/knowledge-filter",
    {
      name: data.name,
      description: data.description ?? "",
      queryData: data.queryData,
    },
  );

  if (response.status < 200 || response.status >= 300) {
    const errorMessage =
      (response.data as { error?: string }).error ||
      "Failed to create knowledge filter";
    throw new Error(errorMessage);
  }

  return response.data;
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
