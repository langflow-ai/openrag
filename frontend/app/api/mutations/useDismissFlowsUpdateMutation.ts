import { useMutation, useQueryClient } from "@tanstack/react-query";

interface DismissFlowsUpdateVariables {
  flow_types?: string[];
}

export function useDismissFlowsUpdateMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (variables?: DismissFlowsUpdateVariables) => {
      const response = await fetch("/api/settings/flows/dismiss-update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(variables || {}),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || "Failed to dismiss flow updates");
      }

      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["flows", "updates-available"],
      });
    },
  });
}
