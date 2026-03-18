"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { useConnectConnectorMutation } from "@/app/api/mutations/useConnectConnectorMutation";
import { useDisconnectConnectorMutation } from "@/app/api/mutations/useDisconnectConnectorMutation";
import {
  type Connector as QueryConnector,
  useGetConnectorsQuery,
} from "@/app/api/queries/useGetConnectorsQuery";
import AwsLogo from "@/components/icons/aws-logo";
import GoogleDriveIcon from "@/components/icons/google-drive-logo";
import IBMCOSIcon from "@/components/icons/ibm-cos-icon";
import OneDriveIcon from "@/components/icons/one-drive-logo";
import SharePointIcon from "@/components/icons/share-point-logo";
import { useAuth } from "@/contexts/auth-context";
import ConnectorCard, { type Connector } from "./connector-card";
import ConnectorsSkeleton from "./connectors-skeleton";
import IBMCOSSettingsDialog from "./ibm-cos-settings-dialog";
import S3SettingsDialog from "./s3-settings-dialog";

export default function ConnectorCards() {
  const { isAuthenticated, isNoAuthMode, isIbmAuthMode } = useAuth();
  const router = useRouter();
  const [ibmCOSDialogOpen, setIBMCOSDialogOpen] = useState(false);
  const [s3DialogOpen, setS3DialogOpen] = useState(false);

  const { data: queryConnectors = [], isLoading: connectorsLoading } =
    useGetConnectorsQuery({
      enabled: isAuthenticated || isNoAuthMode,
    });

  const connectMutation = useConnectConnectorMutation();
  const disconnectMutation = useDisconnectConnectorMutation();

  const getConnectorIcon = useCallback((iconName: string) => {
    const iconMap: { [key: string]: React.ReactElement } = {
      "google-drive": <GoogleDriveIcon />,
      sharepoint: <SharePointIcon />,
      onedrive: <OneDriveIcon />,
      "ibm-cos": <IBMCOSIcon />,
      "aws-s3": <AwsLogo />,
    };
    return (
      iconMap[iconName] || (
        <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          ?
        </div>
      )
    );
  }, []);

  const connectors = queryConnectors
    .filter((c) => {
      if (c.type === "ibm_cos" || c.type === "aws_s3") return isIbmAuthMode;
      return true;
    })
    .map((c) => ({
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

  // Connectors that use a settings dialog instead of OAuth for configuration
  const getConfigureHandler = (connector: Connector) => {
    if (connector.type === "ibm_cos") {
      return () => setIBMCOSDialogOpen(true);
    }
    if (connector.type === "aws_s3") {
      return () => setS3DialogOpen(true);
    }
    return undefined;
  };

  if (!connectorsLoading && connectors.length === 0) {
    return null;
  }

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

      <IBMCOSSettingsDialog
        open={ibmCOSDialogOpen}
        setOpen={setIBMCOSDialogOpen}
      />
      <S3SettingsDialog open={s3DialogOpen} setOpen={setS3DialogOpen} />
    </>
  );
}
