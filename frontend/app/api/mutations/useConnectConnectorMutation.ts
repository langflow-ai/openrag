import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "@/contexts/auth-context";
import { encodeBase64 } from "@/lib/utils";
import type {
  Connector,
  ConnectorsMutationContext,
} from "../queries/useGetConnectorsQuery";
import {
  connectorsQueryFilter,
  restoreConnectorQueries,
  snapshotConnectorQueries,
} from "../queries/useGetConnectorsQuery";

interface ConnectResponse {
  connection_id: string;
  oauth_config?: {
    authorization_endpoint: string;
    client_id: string;
    scopes: string[];
    redirect_uri: string;
    prompt?: string;
  };
}

export const useConnectConnectorMutation = () => {
  const queryClient = useQueryClient();
  const { isIbmAuthMode } = useAuth();

  return useMutation({
    mutationFn: async ({
      connector,
      redirectUri,
      purpose = "data_source",
    }: {
      connector: Connector;
      redirectUri: string;
      /** "test" runs a Test Connection check (see Connector Settings) and does
       * not persist a data-source connection on success. */
      purpose?: "data_source" | "test";
    }): Promise<ConnectResponse> => {
      const response = await fetch("/api/auth/init", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          connector_type: connector.type,
          purpose,
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
    onMutate: async (): Promise<ConnectorsMutationContext> => {
      await queryClient.cancelQueries(connectorsQueryFilter);
      return snapshotConnectorQueries(queryClient);
    },
    onError: (err, _vars, context) => {
      restoreConnectorQueries(queryClient, context);
      toast.error(err.message);
    },
    onSuccess: (result, { connector, purpose = "data_source" }) => {
      if (result.oauth_config) {
        localStorage.setItem("connecting_connector_id", result.connection_id);
        localStorage.setItem("connecting_connector_type", connector.type);
        localStorage.setItem("auth_purpose", purpose);
        if (purpose === "test") {
          localStorage.setItem(
            "test_connection_return_tab",
            "connector-access",
          );
        } else {
          localStorage.removeItem("test_connection_return_tab");
        }

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
          `prompt=${result.oauth_config.prompt ?? "consent"}&` +
          `state=${encodeURIComponent(state)}`;

        window.location.href = authUrl;
      } else {
        // Direct-auth connector (bucket-kind) — credentials already verified,
        // no OAuth redirect needed. Refresh connector status.
        queryClient.invalidateQueries(connectorsQueryFilter);
        toast.success(`${connector.name} connected successfully`);
      }
    },
    onSettled: (_result, error) => {
      if (error) {
        queryClient.invalidateQueries(connectorsQueryFilter);
      }
    },
  });
};
