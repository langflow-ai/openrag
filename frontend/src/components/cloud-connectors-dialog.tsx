"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { UnifiedCloudPicker, CloudFile } from "@/components/cloud-picker";
import { Loader2 } from "lucide-react";

// CloudFile interface is now imported from the unified cloud picker

interface CloudConnector {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  status: "not_connected" | "connecting" | "connected" | "error";
  type: string;
  connectionId?: string;
  clientId: string;
  hasAccessToken: boolean;
  accessTokenError?: string;
}

interface CloudConnectorsDialogProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onFileSelected?: (files: CloudFile[], connectorType: string) => void;
}

export function CloudConnectorsDialog({
  isOpen,
  onOpenChange,
  onFileSelected,
}: CloudConnectorsDialogProps) {
  const [connectors, setConnectors] = useState<CloudConnector[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedFiles, setSelectedFiles] = useState<{
    [connectorId: string]: CloudFile[];
  }>({});
  const [connectorAccessTokens, setConnectorAccessTokens] = useState<{
    [connectorType: string]: string;
  }>({});
  const [activePickerType, setActivePickerType] = useState<string | null>(null);

  const getConnectorIcon = (iconName: string) => {
    const iconMap: { [key: string]: React.ReactElement } = {
      "google-drive": (
        <div className="w-8 h-8 bg-blue-600 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          G
        </div>
      ),
      sharepoint: (
        <div className="w-8 h-8 bg-blue-700 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          SP
        </div>
      ),
      onedrive: (
        <div className="w-8 h-8 bg-blue-400 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          OD
        </div>
      ),
    };
    return (
      iconMap[iconName] || (
        <div className="w-8 h-8 bg-gray-500 rounded flex items-center justify-center text-white font-bold leading-none shrink-0">
          ?
        </div>
      )
    );
  };

  const fetchConnectorStatuses = useCallback(async () => {
    if (!isOpen) return;

    setIsLoading(true);
    try {
      // Fetch available connectors from backend
      const connectorsResponse = await fetch("/api/connectors");
      if (!connectorsResponse.ok) {
        throw new Error("Failed to load connectors");
      }

      const connectorsResult = await connectorsResponse.json();
      const connectorTypes = Object.keys(connectorsResult.connectors);

      // Filter to only cloud connectors
      const cloudConnectorTypes = connectorTypes.filter(
        (type) =>
          ["google_drive", "onedrive", "sharepoint"].includes(type) &&
          connectorsResult.connectors[type].available,
      );

      // Initialize connectors list
      const initialConnectors = cloudConnectorTypes.map((type) => ({
        id: type,
        name: connectorsResult.connectors[type].name,
        description: connectorsResult.connectors[type].description,
        icon: getConnectorIcon(connectorsResult.connectors[type].icon),
        status: "not_connected" as const,
        type: type,
        hasAccessToken: false,
        accessTokenError: undefined,
        clientId: "",
      }));

      setConnectors(initialConnectors);

      // Check status for each cloud connector type
      for (const connectorType of cloudConnectorTypes) {
        try {
          const response = await fetch(
            `/api/connectors/${connectorType}/status`,
          );
          if (response.ok) {
            const data = await response.json();
            const connections = data.connections || [];
            const activeConnection = connections.find(
              (conn: { connection_id: string; is_active: boolean }) =>
                conn.is_active,
            );
            const isConnected = activeConnection !== undefined;

            let hasAccessToken = false;
            let accessTokenError: string | undefined = undefined;

            // Try to get access token for connected connectors
            if (isConnected && activeConnection) {
              try {
                const tokenResponse = await fetch(
                  `/api/connectors/${connectorType}/token?connection_id=${activeConnection.connection_id}`,
                );
                if (tokenResponse.ok) {
                  const tokenData = await tokenResponse.json();
                  if (tokenData.access_token) {
                    hasAccessToken = true;
                    setConnectorAccessTokens((prev) => ({
                      ...prev,
                      [connectorType]: tokenData.access_token,
                    }));
                  }
                } else {
                  const errorData = await tokenResponse
                    .json()
                    .catch(() => ({ error: "Token unavailable" }));
                  accessTokenError =
                    errorData.error || "Access token unavailable";
                }
              } catch {
                accessTokenError = "Failed to fetch access token";
              }
            }

            setConnectors((prev) =>
              prev.map((c) =>
                c.type === connectorType
                  ? {
                      ...c,
                      status: isConnected ? "connected" : "not_connected",
                      connectionId: activeConnection?.connection_id,
                      clientId: activeConnection?.client_id,
                      hasAccessToken,
                      accessTokenError,
                    }
                  : c,
              ),
            );
          }
        } catch (error) {
          console.error(`Failed to check status for ${connectorType}:`, error);
        }
      }
    } catch (error) {
      console.error("Failed to load cloud connectors:", error);
    } finally {
      setIsLoading(false);
    }
  }, [isOpen]);

  const handleFileSelection = (connectorId: string, files: CloudFile[]) => {
    setSelectedFiles((prev) => ({
      ...prev,
      [connectorId]: files,
    }));

    onFileSelected?.(files, connectorId);
  };

  useEffect(() => {
    fetchConnectorStatuses();
  }, [fetchConnectorStatuses]);

  return (
    <Dialog open={isOpen} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] overflow-hidden">
        <DialogHeader>
          <DialogTitle>Cloud File Connectors</DialogTitle>
          <DialogDescription>
            Select files or folders from your connected cloud storage providers
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin mr-2" />
              Loading connectors...
            </div>
          ) : connectors.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No cloud connectors available. Configure them in Settings first.
            </div>
          ) : (
            <div className="space-y-6">
              {/* Service Buttons Row */}
              <div className="flex flex-wrap gap-3 justify-center">
                {connectors
                  .filter((connector) => connector.status === "connected")
                  .map((connector) => (
                    <Button
                      key={connector.id}
                      variant={
                        connector.hasAccessToken ? "default" : "secondary"
                      }
                      disabled={!connector.hasAccessToken}
                      title={
                        !connector.hasAccessToken
                          ? connector.accessTokenError ||
                            "Access token required - try reconnecting your account"
                          : `Select files or folders from ${connector.name}`
                      }
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (connector.hasAccessToken) {
                          setActivePickerType(connector.id);
                        }
                      }}
                      className="min-w-[120px]"
                    >
                      {connector.name}
                    </Button>
                  ))}
              </div>

              {connectors.every((c) => c.status !== "connected") && (
                <div className="text-center py-8 text-muted-foreground">
                  <p>No connected cloud providers found.</p>
                  <p className="text-sm mt-1">
                    Go to Settings to connect your cloud storage accounts.
                  </p>
                </div>
              )}

              {/* Render unified picker inside dialog */}
              {activePickerType &&
                connectors.find((c) => c.id === activePickerType) &&
                (() => {
                  const connector = connectors.find(
                    (c) => c.id === activePickerType,
                  )!;

                  return (
                    <div className="mt-6">
                      <UnifiedCloudPicker
                        provider={
                          connector.type as
                            | "google_drive"
                            | "onedrive"
                            | "sharepoint"
                        }
                        onFileSelected={(files) => {
                          handleFileSelection(connector.id, files);
                          setActivePickerType(null);
                        }}
                        selectedFiles={selectedFiles[connector.id] || []}
                        isAuthenticated={connector.status === "connected"}
                        accessToken={connectorAccessTokens[connector.type]}
                        onPickerStateChange={() => {}}
                        clientId={connector.clientId}
                        isIngesting={false}
                      />
                    </div>
                  );
                })()}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
