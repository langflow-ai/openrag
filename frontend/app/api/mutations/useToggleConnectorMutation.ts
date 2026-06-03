import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Connector } from "../queries/useGetConnectorsQuery";

interface ToggleConnectorVariables {
  connector: Connector;
  enabled: boolean;
}

export const useToggleConnectorMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ connector, enabled }: ToggleConnectorVariables) => {
      const response = await fetch(
        `/api/connectors/${connector.type}/enabled`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        },
      );

      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(
          result?.detail?.error ||
            result.error ||
            `Failed to update ${connector.name}`,
        );
      }
      return response.json();
    },
    onMutate: async ({ connector, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ["connectors"] });

      const previousConnectors = queryClient.getQueryData<Connector[]>([
        "connectors",
      ]);

      if (previousConnectors) {
        queryClient.setQueryData<Connector[]>(
          ["connectors"],
          previousConnectors.map((c) =>
            c.type === connector.type ? { ...c, enabled } : c,
          ),
        );
      }

      return { previousConnectors };
    },
    onError: (err, { connector }, context) => {
      if (context?.previousConnectors) {
        queryClient.setQueryData(["connectors"], context.previousConnectors);
      }
      toast.error(`Failed to update ${connector.name}: ${err.message}`);
    },
    onSuccess: (_, { connector, enabled }) => {
      toast.success(
        `${connector.name} ${enabled ? "enabled" : "disabled"} for the workspace`,
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
    },
  });
};
