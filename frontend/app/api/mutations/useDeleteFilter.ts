import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface DeleteFilterRequest {
  id: string;
}

export interface DeleteFilterResponse {
  success: boolean;
  message?: string;
}

async function deleteFilter(
  data: DeleteFilterRequest,
): Promise<DeleteFilterResponse> {
  const response = await apiClient.delete<DeleteFilterResponse>(
    `/knowledge-filter/${data.id}`,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorMessage =
      (response.data as { error?: string }).error ||
      "Failed to delete knowledge filter";
    throw new Error(errorMessage);
  }

  return response.data || { success: true };
}

export const useDeleteFilter = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteFilter,
    onSuccess: () => {
      // Invalidate filters queries so UI refreshes automatically
      queryClient.invalidateQueries({ queryKey: ["knowledge-filters"] });
    },
  });
};
