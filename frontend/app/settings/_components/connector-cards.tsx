"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { useConnectConnectorMutation } from "@/app/api/mutations/useConnectConnectorMutation";
import { useDisconnectConnectorMutation } from "@/app/api/mutations/useDisconnectConnectorMutation";
import {
  type Connector as QueryConnector,
  useGetConnectorsQuery,
} from "@/app/api/queries/useGetConnectorsQuery";
import { useAuth } from "@/contexts/auth-context";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  getConnectorDescriptor,
  getConnectorDescriptors,
} from "@/lib/connectors/registry";
import ConnectorCard, { type Connector } from "./connector-card";
import ConnectorsSkeleton from "./connectors-skeleton";

export default function ConnectorCards() {
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const isCloudBrand = useIsCloudBrand();
  const router = useRouter();
  const [openDialog, setOpenDialog] = useState<string | null>(null);

  const { data: queryConnectors = [], isLoading: connectorsLoading } =
    useGetConnectorsQuery({
      enabled: isAuthenticated || isNoAuthMode,
    });

  const connectMutation = useConnectConnectorMutation();
  const disconnectMutation = useDisconnectConnectorMutation();

  const getConnectorIcon = useCallback((connectorType: string) => {
    const Icon = getConnectorDescriptor(connectorType)?.Icon;
    if (!Icon) {
      return (
        <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          ?
        </div>
      );
    }
    return <Icon />;
  }, []);

  const connectors = queryConnectors
    .filter((c) => {
      if (c.type === "ibm_cos" || c.type === "aws_s3") return isIbmAuthMode;
      if (isCloudBrand && c.type === "onedrive") return false;
      return true;
    })
    .map((c) => ({
      ...c,
      icon: getConnectorIcon(c.type),
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

  const getConfigureHandler = (connector: Connector) => {
    const descriptor = getConnectorDescriptor(connector.type);
    if (descriptor?.SettingsDialog) {
      return () => setOpenDialog(connector.type);
    }
    return undefined;
  };

  if (!connectorsLoading && connectors.length === 0) {
    return null;
  }

  const dialogDescriptors = getConnectorDescriptors().filter(
    (d) => d.SettingsDialog,
  );

  return (
    <>
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
              onConfigure={getConfigureHandler(connector)}
            />
          ))
        )}
      </div>

      {dialogDescriptors.map((descriptor) => {
        const Dialog = descriptor.SettingsDialog!;
        return (
          <Dialog
            key={descriptor.connectorType}
            open={openDialog === descriptor.connectorType}
            setOpen={(open: boolean) =>
              setOpenDialog(open ? descriptor.connectorType : null)
            }
          />
        );
      })}
    </>
  );
}
