"use client";

import { useConnectConnectorMutation } from "@/app/api/mutations/useConnectConnectorMutation";
import { useDisconnectConnectorMutation } from "@/app/api/mutations/useDisconnectConnectorMutation";
import { useGetConnectorsQuery, type Connector as QueryConnector } from "@/app/api/queries/useGetConnectorsQuery";
import GoogleDriveIcon from "@/components/icons/google-drive-logo";
import OneDriveIcon from "@/components/icons/one-drive-logo";
import SharePointIcon from "@/components/icons/share-point-logo";
import { useAuth } from "@/contexts/auth-context";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import ConnectorCard, { type Connector } from "./connector-card";
import ConnectorsSkeleton from "./connectors-skeleton";

export default function ConnectorCards() {
    const { isAuthenticated, isNoAuthMode } = useAuth();
    const router = useRouter();

    const { data: queryConnectors = [], isLoading: connectorsLoading } = useGetConnectorsQuery({
        enabled: isAuthenticated || isNoAuthMode,
    });

    const connectMutation = useConnectConnectorMutation();
    const disconnectMutation = useDisconnectConnectorMutation();

    const getConnectorIcon = useCallback((iconName: string) => {
        const iconMap: { [key: string]: React.ReactElement } = {
            "google-drive": <GoogleDriveIcon />,
            sharepoint: <SharePointIcon />,
            onedrive: <OneDriveIcon />,
        };
        return (
            iconMap[iconName] || (
                <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
                    ?
                </div>
            )
        );
    }, []);

    const connectors = queryConnectors.map((c) => ({
        ...c,
        icon: getConnectorIcon(c.icon),
    })) as Connector[];

    const handleConnect = async (connector: Connector) => {
        connectMutation.mutate({
            connector: connector as unknown as QueryConnector,
            redirectUri: `${window.location.origin}/auth/callback`,
        });
    };

    const handleDisconnect = async (connector: Connector) => {
        disconnectMutation.mutate(connector as unknown as QueryConnector);
    };

    const navigateToKnowledgePage = (connector: Connector) => {
        const provider = connector.type.replace(/-/g, "_");
        router.push(`/upload/${provider}`);
    };

    if (!connectorsLoading && connectors.length === 0) {
        return null;
    }

    return (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {connectorsLoading ? (
                <>
                    <ConnectorsSkeleton />
                    <ConnectorsSkeleton />
                    <ConnectorsSkeleton />
                </>
            ) : (
                connectors.map((connector) => (
                    <ConnectorCard
                        key={connector.id}
                        connector={connector}
                        isConnecting={
                            connectMutation.isPending &&
                            connectMutation.variables?.connector.id === connector.id
                        }
                        isDisconnecting={
                            disconnectMutation.isPending &&
                            (disconnectMutation.variables as any)?.type === connector.type
                        }
                        onConnect={handleConnect}
                        onDisconnect={handleDisconnect}
                        onNavigateToKnowledge={navigateToKnowledgePage}
                    />
                ))
            )}
        </div>
    );
}
