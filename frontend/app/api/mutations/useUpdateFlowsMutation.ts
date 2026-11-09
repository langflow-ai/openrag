import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface UpdateFlowsVariables {
  flow_types: string[];
  backup_custom: boolean;
}

export type FlowUpdateResult = {
  flow_type: string;
  success: boolean;
  error?: string;
  backup_path?: string;
  backup_flow_id?: string;
};

export function useUpdateFlowsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (variables: UpdateFlowsVariables) => {
      const response = await apiClient.post(
        "/settings/flows/update",
        variables,
      );

      if (response.status < 200 || response.status >= 300) {
        const errorData = response.data ?? {};
        throw new Error(errorData.error || "Failed to update flows");
      }

      const data = response.data;
      return data.results as FlowUpdateResult[];
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
    },
  });
}
