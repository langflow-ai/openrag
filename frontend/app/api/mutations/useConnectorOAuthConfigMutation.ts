import { useMutation, useQueryClient } from "@tanstack/react-query";
import { connectorOAuthConfigQueryKey } from "../queries/useConnectorOAuthConfigQuery";

export interface SaveConnectorOAuthConfigPayload {
  credentialKey: string;
  client_id?: string;
  client_secret?: string;
}

async function saveConnectorOAuthConfig({
  credentialKey,
  client_id,
  client_secret,
}: SaveConnectorOAuthConfigPayload) {
  const res = await fetch(
    `/api/connectors/oauth-config/${encodeURIComponent(credentialKey)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id, client_secret }),
    },
  );
  const data = await res.json();
  if (!res.ok)
    throw new Error(data.error || "Failed to save connector credentials");
  return data;
}

export function useSaveConnectorOAuthConfigMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: saveConnectorOAuthConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: connectorOAuthConfigQueryKey });
    },
  });
}

async function clearConnectorOAuthConfig(credentialKey: string) {
  const res = await fetch(
    `/api/connectors/oauth-config/${encodeURIComponent(credentialKey)}`,
    { method: "DELETE" },
  );
  const data = await res.json();
  if (!res.ok)
    throw new Error(data.error || "Failed to clear connector credentials");
  return data;
}

export function useClearConnectorOAuthConfigMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: clearConnectorOAuthConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: connectorOAuthConfigQueryKey });
    },
  });
}
