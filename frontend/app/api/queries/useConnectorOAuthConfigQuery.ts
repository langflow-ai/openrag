import { useQuery } from "@tanstack/react-query";

export interface ConnectorOAuthConfigStatus {
  client_id_set: boolean;
  client_id: string | null;
  secret_source: "override" | "env" | "none";
  env_client_id_set: boolean;
}

export type ConnectorOAuthConfigMap = Record<
  string,
  ConnectorOAuthConfigStatus
>;

async function fetchConnectorOAuthConfig(): Promise<ConnectorOAuthConfigMap> {
  const res = await fetch("/api/connectors/oauth-config");
  if (!res.ok) throw new Error("Failed to fetch connector OAuth config");
  const data = await res.json();
  return data.credentials as ConnectorOAuthConfigMap;
}

export const connectorOAuthConfigQueryKey = ["connector-oauth-config"] as const;

export function useConnectorOAuthConfigQuery(options?: { enabled?: boolean }) {
  return useQuery<ConnectorOAuthConfigMap>({
    queryKey: connectorOAuthConfigQueryKey,
    queryFn: fetchConnectorOAuthConfig,
    enabled: options?.enabled ?? true,
    staleTime: 0,
  });
}
