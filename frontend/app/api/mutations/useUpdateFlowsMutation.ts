import { useMutation, useQueryClient } from "@tanstack/react-query";

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
      const response = await fetch("/api/settings/flows/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(variables),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || "Failed to update flows");
      }

      const data = await response.json();
      return data.results as FlowUpdateResult[];
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["flows"] });
    },
  });
}
