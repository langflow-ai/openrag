"use client";

import { useConnectConnectorMutation } from "@/app/api/mutations/useConnectConnectorMutation";
import { useDisconnectConnectorMutation } from "@/app/api/mutations/useDisconnectConnectorMutation";
import { useGetConnectorsQuery, type Connector as QueryConnector } from "@/app/api/queries/useGetConnectorsQuery";
import GoogleDriveIcon from "@/components/icons/google-drive-logo";
import OneDriveIcon from "@/components/icons/one-drive-logo";
import SharePointIcon from "@/components/icons/share-point-logo";
import { Button } from "@/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/contexts/auth-context";
import { cn } from "@/lib/utils";
import { Loader2, PlugZap, Plus, RefreshCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import ConnectorsSkeleton from "./connectors-skeleton";

interface SyncResult {
    processed?: number;
    added?: number;
    errors?: number;
    skipped?: number;
    total?: number;
}

interface Connector extends Omit<QueryConnector, "icon"> {
    icon: React.ReactNode;
}

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
                    <Card key={connector.id} className="relative flex flex-col">
                        <CardHeader className="pb-2">
                            <div className="flex flex-col items-start justify-between">
                                <div className="flex flex-col gap-3">
                                    <div className="mb-1">
                                        <div
                                            className={cn(
                                                "w-8 h-8 rounded flex items-center justify-center border",
                                                connector?.available
                                                    ? "bg-white"
                                                    : "bg-muted grayscale",
                                            )}
                                        >
                                            {connector.icon}
                                        </div>
                                    </div>
                                    <CardTitle className="flex flex-row items-center gap-2">
                                        {connector.name}
                                    </CardTitle>
                                    <CardDescription className="text-sm">
                                        {connector?.available
                                            ? `${connector.name} is configured.`
                                            : "Not configured."}
                                    </CardDescription>
                                </div>
                            </div>
                        </CardHeader>
                        <CardContent className="flex-1 flex flex-col justify-end space-y-4">
                            {connector?.available ? (
                                <div className="space-y-3">
                                    {connector?.status === "connected" && connector?.connectionId ? (
                                        <>
                                            <div className="flex gap-2 overflow-hidden w-full">
                                                <Button
                                                    variant="outline"
                                                    onClick={() => navigateToKnowledgePage(connector)}
                                                    disabled={
                                                        (disconnectMutation.isPending &&
                                                            (disconnectMutation.variables as any)?.type ===
                                                            connector.type) ||
                                                        (connectMutation.isPending &&
                                                            connectMutation.variables?.connector.id ===
                                                            connector.id)
                                                    }
                                                    className="cursor-pointer !text-sm truncate"
                                                    size="md"
                                                >
                                                    <Plus className="h-4 w-4" />
                                                    <span className="text-mmd truncate">
                                                        Add Knowledge
                                                    </span>
                                                </Button>
                                                <Button
                                                    variant="outline"
                                                    onClick={() => handleConnect(connector)}
                                                    disabled={
                                                        (connectMutation.isPending &&
                                                            connectMutation.variables?.connector.id ===
                                                            connector.id) ||
                                                        (disconnectMutation.isPending &&
                                                            (disconnectMutation.variables as any)?.type ===
                                                            connector.type)
                                                    }
                                                    className="cursor-pointer"
                                                    size="iconMd"
                                                >
                                                    {connectMutation.isPending &&
                                                        connectMutation.variables?.connector.id ===
                                                        connector.id ? (
                                                        <RefreshCcw className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <RefreshCcw className="h-4 w-4" />
                                                    )}
                                                </Button>
                                                <Button
                                                    variant="outline"
                                                    onClick={() => handleDisconnect(connector)}
                                                    disabled={
                                                        (disconnectMutation.isPending &&
                                                            (disconnectMutation.variables as any)?.type ===
                                                            connector.type) ||
                                                        (connectMutation.isPending &&
                                                            connectMutation.variables?.connector.id ===
                                                            connector.id)
                                                    }
                                                    className="cursor-pointer text-destructive hover:text-destructive"
                                                    size="iconMd"
                                                >
                                                    {disconnectMutation.isPending &&
                                                        (disconnectMutation.variables as any)?.type ===
                                                        connector.type ? (
                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <Trash2 className="h-4 w-4" />
                                                    )}
                                                </Button>
                                            </div>
                                        </>
                                    ) : (
                                        <Button
                                            onClick={() => handleConnect(connector)}
                                            disabled={
                                                (connectMutation.isPending &&
                                                    connectMutation.variables?.connector.id ===
                                                    connector.id)
                                            }
                                            className="w-full cursor-pointer"
                                            size="sm"
                                        >
                                            {(connectMutation.isPending &&
                                                connectMutation.variables?.connector.id ===
                                                connector.id) ? (
                                                <>
                                                    <Loader2 className="h-4 w-4 animate-spin" />
                                                    Connecting...
                                                </>
                                            ) : (
                                                <>
                                                    <PlugZap className="h-4 w-4" />
                                                    Connect
                                                </>
                                            )}
                                        </Button>
                                    )}
                                </div>
                            ) : (
                                <div className="text-sm text-muted-foreground">
                                    <p>
                                        See our{" "}
                                        <Link
                                            className="text-accent-pink-foreground"
                                            href="https://docs.openr.ag/knowledge#oauth-ingestion"
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            Cloud Connectors installation guide
                                        </Link>{" "}
                                        for more detail.
                                    </p>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                ))
            )}
        </div>
    );
}
