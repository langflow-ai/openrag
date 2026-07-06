import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type {
  Connector,
  ConnectorsMutationContext,
} from "../queries/useGetConnectorsQuery";
import {
  connectorsQueryFilter,
  restoreConnectorQueries,
  snapshotConnectorQueries,
  updateAllConnectorQueries,
} from "../queries/useGetConnectorsQuery";

export const useDisconnectConnectorMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (connector: Connector) => {
      const response = await fetch(
        `/api/connectors/${connector.type}/disconnect`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok) {
        const result = await response.json();
        throw new Error(
          result.error || `Failed to disconnect ${connector.name}`,
        );
      }
      return response.json();
    },
    onMutate: async (connector): Promise<ConnectorsMutationContext> => {
      await queryClient.cancelQueries(connectorsQueryFilter);
      const context = snapshotConnectorQueries(queryClient);

      updateAllConnectorQueries(queryClient, (connectors) =>
        connectors.map((c) =>
          c.type === connector.type
            ? { ...c, status: "not_connected", connectionId: undefined }
            : c,
        ),
      );

      return context;
    },
    onError: (err, connector, context) => {
      restoreConnectorQueries(queryClient, context);
      toast.error(`Failed to disconnect ${connector.name}: ${err.message}`);
    },
    onSuccess: (_, connector) => {
      toast.success(`${connector.name} disconnected`);
    },
    onSettled: () => {
      // Always refetch after error or success to ensure we have the correct data
      queryClient.invalidateQueries(connectorsQueryFilter);
    },
  });
};
