import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { ConnectorAccessItem } from "../queries/useGetConnectorAccessQuery";

export const useUpdateConnectorAccessMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (
      access: Record<string, boolean>,
    ): Promise<ConnectorAccessItem[]> => {
      const response = await fetch("/api/connectors/user-access", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || "Failed to update connector access");
      }
      const data = await response.json();
      return Array.isArray(data.connectors) ? data.connectors : [];
    },
    onSuccess: (connectors) => {
      queryClient.setQueryData(["connector-user-access"], connectors);
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
      toast.success("Connector access saved");
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
};
