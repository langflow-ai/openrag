import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

interface GoogleDriveFile {
    id: string;
    name: string;
    mimeType: string;
    webViewLink?: string;
    iconLink?: string;
}

interface OneDriveFile {
    id: string;
    name: string;
    mimeType?: string;
    webUrl?: string;
    driveItem?: {
        file?: { mimeType: string };
        folder?: unknown;
    };
}

export interface Connector {
    id: string;
    name: string;
    description: string;
    icon: string; // The icon name from the API
    status: "not_connected" | "connected" | "error";
    type: string;
    connectionId?: string;
    clientId?: string;
    baseUrl?: string;
    access_token?: string;
    selectedFiles?: GoogleDriveFile[] | OneDriveFile[];
    available?: boolean;
}

interface Connection {
    connection_id: string;
    is_active: boolean;
    is_authenticated?: boolean;
    created_at: string;
    last_sync?: string;
    client_id?: string;
    base_url?: string;
}

export interface GetConnectorsResponse {
    connectors: Connector[];
}

export const useGetConnectorsQuery = (
    options?: Omit<UseQueryOptions<Connector[]>, "queryKey" | "queryFn">,
) => {
    async function getConnectors(): Promise<Connector[]> {
        const connectorsResponse = await fetch("/api/connectors");
        if (!connectorsResponse.ok) {
            throw new Error("Failed to fetch available connectors");
        }

        const { connectors: connectorsMap } = await connectorsResponse.json();
        const connectorTypes = Object.keys(connectorsMap);

        const connectorsWithStatus = await Promise.all(
            connectorTypes.map(async (type) => {
                const connectorData = connectorsMap[type];
                const statusResponse = await fetch(`/api/connectors/${type}/status`);

                let status: Connector["status"] = "not_connected";
                let connectionId: string | undefined;

                if (statusResponse.ok) {
                    const statusData = await statusResponse.json();
                    const connections = statusData.connections || [];
                    const activeConnection = connections.find(
                        (conn: Connection) => conn.is_active && conn.is_authenticated,
                    );

                    if (activeConnection) {
                        status = "connected";
                        connectionId = activeConnection.connection_id;
                        return {
                            id: type,
                            name: connectorData.name,
                            description: connectorData.description,
                            icon: connectorData.icon,
                            status,
                            type,
                            connectionId,
                            clientId: activeConnection.client_id,
                            baseUrl: activeConnection.base_url,
                            available: connectorData.available,
                        } as Connector;
                    }
                }

                return {
                    id: type,
                    name: connectorData.name,
                    description: connectorData.description,
                    icon: connectorData.icon,
                    status,
                    type,
                    connectionId,
                    available: connectorData.available,
                } as Connector;
            }),
        );

        return connectorsWithStatus;
    }

    return useQuery({
        queryKey: ["connectors"],
        queryFn: getConnectors,
        refetchOnMount: "always",
        ...options,
    });
};
