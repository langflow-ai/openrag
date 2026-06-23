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
  backup_content?: string;
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
        throw new Error("Failed to update flows");
      }

      const data = await response.json();
      return data.results as FlowUpdateResult[];
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["flows"] });
    },
  });
}
