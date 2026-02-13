import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Connector } from "../queries/useGetConnectorsQuery";

export const useDisconnectConnectorMutation = () => {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (connector: Connector) => {
            const response = await fetch(`/api/connectors/${connector.type}/disconnect`, {
                method: "DELETE",
            });

            if (!response.ok) {
                const result = await response.json();
                throw new Error(result.error || `Failed to disconnect ${connector.name}`);
            }
            return response.json();
        },
        onMutate: async (connector) => {
            // Cancel any outgoing refetches (so they don't overwrite our optimistic update)
            await queryClient.cancelQueries({ queryKey: ["connectors"] });

            // Snapshot the previous value
            const previousConnectors = queryClient.getQueryData<Connector[]>(["connectors"]);

            // Optimistically update to the new value
            if (previousConnectors) {
                queryClient.setQueryData<Connector[]>(["connectors"],
                    previousConnectors.map((c) =>
                        c.type === connector.type
                            ? { ...c, status: "not_connected", connectionId: undefined }
                            : c
                    )
                );
            }

            return { previousConnectors };
        },
        onError: (err, connector, context) => {
            // If the mutation fails, use the context returned from onMutate to roll back
            if (context?.previousConnectors) {
                queryClient.setQueryData(["connectors"], context.previousConnectors);
            }
            toast.error(`Failed to disconnect ${connector.name}: ${err.message}`);
        },
        onSuccess: (_, connector) => {
            toast.success(`${connector.name} disconnected`);
        },
        onSettled: () => {
            // Always refetch after error or success to ensure we have the correct data
            queryClient.invalidateQueries({ queryKey: ["connectors"] });
        },
    });
};
