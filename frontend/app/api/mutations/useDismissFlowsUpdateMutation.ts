import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface DismissFlowsUpdateVariables {
  flow_types?: string[];
}

export function useDismissFlowsUpdateMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (variables?: DismissFlowsUpdateVariables) => {
      const response = await apiClient.post(
        "/settings/flows/dismiss-update",
        variables || {},
      );

      if (response.status < 200 || response.status >= 300) {
        const errorData = response.data as { error?: string };
        throw new Error(errorData.error || "Failed to dismiss flow updates");
      }

      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["flows", "updates-available"],
      });
    },
  });
}
