import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
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
  const res = await apiClient.put(
    `/connectors/oauth-config/${encodeURIComponent(credentialKey)}`,
    { client_id, client_secret },
  );
  const data = res.data ?? {};
  if (res.status < 200 || res.status >= 300)
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
  const res = await apiClient.delete(
    `/connectors/oauth-config/${encodeURIComponent(credentialKey)}`,
  );
  const data = res.data ?? {};
  if (res.status < 200 || res.status >= 300)
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
