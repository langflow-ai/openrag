import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { encodeBase64 } from "@/lib/utils";
import type { Connector } from "../queries/useGetConnectorsQuery";

interface ConnectResponse {
  connection_id: string;
  oauth_config?: {
    authorization_endpoint: string;
    client_id: string;
    scopes: string[];
    redirect_uri: string;
  };
}

export const useConnectConnectorMutation = () => {
  const queryClient = useQueryClient();
  const { isIbmAuthMode } = useAuth();

  return useMutation({
    mutationFn: async ({
      connector,
      redirectUri,
    }: {
      connector: Connector;
      redirectUri: string;
    }): Promise<ConnectResponse> => {
      const response = await fetch("/api/auth/init", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          connector_type: connector.type,
          purpose: "data_source",
          name: `${connector.name} Connection`,
          redirect_uri: redirectUri,
        }),
      });

      if (!response.ok) {
        const result = await response.json();
        throw new Error(
          result.error || `Failed to initiate connection for ${connector.name}`,
        );
      }
      return response.json();
    },
    onMutate: async ({ connector }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ["connectors"] });

      // Snapshot the previous value
      const previousConnectors = queryClient.getQueryData<Connector[]>([
        "connectors",
      ]);

      return { previousConnectors };
    },
    onError: (err, { connector }, context) => {
      // Roll back if mutation fails
      if (context?.previousConnectors) {
        queryClient.setQueryData(["connectors"], context.previousConnectors);
      }
      toast.error(err.message);
    },
    onSuccess: (result, { connector }) => {
      if (result.oauth_config) {
        localStorage.setItem("connecting_connector_id", result.connection_id);
        localStorage.setItem("connecting_connector_type", connector.type);
        localStorage.setItem("auth_purpose", "data_source");

        const state = isIbmAuthMode
          ? encodeBase64(
              `id=${result.connection_id}&return=${window.location.origin}/auth/callback`,
            )
          : result.connection_id;

        const authUrl =
          `${result.oauth_config.authorization_endpoint}?` +
          `client_id=${result.oauth_config.client_id}&` +
          `response_type=code&` +
          `scope=${result.oauth_config.scopes.join(" ")}&` +
          `redirect_uri=${encodeURIComponent(
            result.oauth_config.redirect_uri,
          )}&` +
          `access_type=offline&` +
          `prompt=select_account&` +
          `state=${encodeURIComponent(state)}`;

        window.location.href = authUrl;
      } else {
        // Direct-auth connector (e.g. IBM COS) — credentials already verified,
        // no OAuth redirect needed. Refresh connector status.
        queryClient.invalidateQueries({ queryKey: ["connectors"] });
        toast.success(`${connector.name} connected successfully`);
      }
    },
  });
};
