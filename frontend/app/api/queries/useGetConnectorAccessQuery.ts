import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface ConnectorAccessItem {
  type: string;
  name: string;
  enabled: boolean;
}

export const useGetConnectorAccessQuery = (
  options?: Omit<
    UseQueryOptions<ConnectorAccessItem[]>,
    "queryKey" | "queryFn"
  >,
) => {
  async function fetchConnectorAccess(): Promise<ConnectorAccessItem[]> {
    const response = await fetch("/api/connectors/user-access");
    if (!response.ok) {
      throw new Error(`Failed to fetch connector access (${response.status})`);
    }
    const data = await response.json();
    return Array.isArray(data.connectors) ? data.connectors : [];
  }

  return useQuery({
    queryKey: ["connector-user-access"],
    queryFn: fetchConnectorAccess,
    ...options,
  });
};
