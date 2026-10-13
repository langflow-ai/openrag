import { type UseQueryOptions, useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

interface TokenResponse {
  access_token: string;
  expires_in?: number;
  token_type?: string;
  error?: string;
}

export const useGetConnectorTokenQuery = (
  {
    connectorType,
    connectionId,
    resource,
  }: {
    connectorType: string;
    connectionId: string | undefined;
    resource?: string;
  },
  options?: Omit<UseQueryOptions<TokenResponse>, "queryKey" | "queryFn">,
) => {
  return useQuery({
    queryKey: ["connector-token", connectorType, connectionId, resource],
    queryFn: async (): Promise<TokenResponse> => {
      if (!connectionId) {
        throw new Error("Connection ID is required for fetching token");
      }

      let url = `/connectors/${connectorType}/token?connection_id=${connectionId}`;
      if (resource) {
        url += `&resource=${encodeURIComponent(resource)}`;
      }

      const response = await apiClient.get<TokenResponse>(url);
      if (response.status < 200 || response.status >= 300) {
        const errorData = response.data ?? {};
        throw new Error(errorData.error || "Failed to fetch access token");
      }

      return response.data;
    },
    enabled: !!connectorType && !!connectionId && (options?.enabled ?? true),
    staleTime: 1000 * 60 * 5, // 5 minutes
    ...options,
  });
};
