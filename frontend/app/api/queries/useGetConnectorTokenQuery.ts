import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

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

            let url = `/api/connectors/${connectorType}/token?connection_id=${connectionId}`;
            if (resource) {
                url += `&resource=${encodeURIComponent(resource)}`;
            }

            const response = await fetch(url);
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || "Failed to fetch access token");
            }

            return response.json();
        },
        enabled: !!connectorType && !!connectionId && (options?.enabled ?? true),
        staleTime: 1000 * 60 * 5, // 5 minutes
        ...options,
    });
};
