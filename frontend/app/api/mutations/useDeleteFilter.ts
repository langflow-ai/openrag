import { useMutation, useQueryClient } from "@tanstack/react-query";

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
  const response = await fetch(`/api/knowledge-filter/${data.id}`, {
    method: "DELETE",
  });

  const json = await response.json().catch(() => ({}));

  if (!response.ok) {
    const errorMessage =
      (json && (json.error as string)) || "Failed to delete knowledge filter";
    throw new Error(errorMessage);
  }

  return (json as DeleteFilterResponse) || { success: true };
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
