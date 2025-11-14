"use client";

import { AlertCircle, ArrowLeft } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { type CloudFile, UnifiedCloudPicker } from "@/components/cloud-picker";
import type { IngestSettings } from "@/components/cloud-picker/types";
import { Button } from "@/components/ui/button";
import { useTask } from "@/contexts/task-context";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// CloudFile interface is now imported from the unified cloud picker

interface CloudConnector {
  id: string;
  name: string;
  description: string;
  status: "not_connected" | "connecting" | "connected" | "error";
  type: string;
  connectionId?: string;
  clientId: string;
  hasAccessToken: boolean;
  accessTokenError?: string;
}

export default function UploadProviderPage() {
  const params = useParams();
  const router = useRouter();
  const provider = params.provider as string;
  const { addTask, tasks } = useTask();

  const [connector, setConnector] = useState<CloudConnector | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
  const [isIngesting, setIsIngesting] = useState<boolean>(false);
  const [currentSyncTaskId, setCurrentSyncTaskId] = useState<string | null>(
    null,
  );
  const [ingestSettings, setIngestSettings] = useState<IngestSettings>({
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: "text-embedding-3-small",
  });

  useEffect(() => {
    const fetchConnectorInfo = async () => {
      setIsLoading(true);
      setError(null);

      try {
        // Fetch available connectors to validate the provider
        const connectorsResponse = await fetch("/api/connectors");
        if (!connectorsResponse.ok) {
          throw new Error("Failed to load connectors");
        }

        const connectorsResult = await connectorsResponse.json();
        const providerInfo = connectorsResult.connectors[provider];

        if (!providerInfo || !providerInfo.available) {
          setError(
            `Cloud provider "${provider}" is not available or configured.`,
          );
          return;
        }

        // Check connector status
        const statusResponse = await fetch(
          `/api/connectors/${provider}/status`,
        );
        if (!statusResponse.ok) {
          throw new Error(`Failed to check ${provider} status`);
        }

        const statusData = await statusResponse.json();
        const connections = statusData.connections || [];
        const activeConnection = connections.find(
          (conn: { is_active: boolean; connection_id: string }) =>
            conn.is_active,
        );
        const isConnected = activeConnection !== undefined;

        let hasAccessToken = false;
        let accessTokenError: string | undefined;

        // Try to get access token for connected connectors
        if (isConnected && activeConnection) {
          try {
            const tokenResponse = await fetch(
              `/api/connectors/${provider}/token?connection_id=${activeConnection.connection_id}`,
            );
            if (tokenResponse.ok) {
              const tokenData = await tokenResponse.json();
              if (tokenData.access_token) {
                hasAccessToken = true;
                setAccessToken(tokenData.access_token);
              }
            } else {
              const errorData = await tokenResponse
                .json()
                .catch(() => ({ error: "Token unavailable" }));
              accessTokenError = errorData.error || "Access token unavailable";
            }
          } catch {
            accessTokenError = "Failed to fetch access token";
          }
        }

        setConnector({
          id: provider,
          name: providerInfo.name,
          description: providerInfo.description,
          status: isConnected ? "connected" : "not_connected",
          type: provider,
          connectionId: activeConnection?.connection_id,
          clientId: activeConnection?.client_id,
          hasAccessToken,
          accessTokenError,
        });
      } catch (error) {
        console.error("Failed to load connector info:", error);
        setError(
          error instanceof Error
            ? error.message
            : "Failed to load connector information",
        );
      } finally {
        setIsLoading(false);
      }
    };

    if (provider) {
      fetchConnectorInfo();
    }
  }, [provider]);

  // Watch for sync task completion and redirect
  useEffect(() => {
    if (!currentSyncTaskId) return;

    const currentTask = tasks.find(
      (task) => task.task_id === currentSyncTaskId,
    );

    if (currentTask && currentTask.status === "completed") {
      // Task completed successfully, show toast and redirect
      setIsIngesting(false);
      setTimeout(() => {
        router.push("/knowledge");
      }, 2000); // 2 second delay to let user see toast
    } else if (currentTask && currentTask.status === "failed") {
      // Task failed, clear the tracking but don't redirect
      setIsIngesting(false);
      setCurrentSyncTaskId(null);
    }
  }, [tasks, currentSyncTaskId, router]);

  const handleFileSelected = (files: CloudFile[]) => {
    setSelectedFiles(files);
    console.log(`Selected ${files.length} item(s) from ${provider}:`, files);
    // You can add additional handling here like triggering sync, etc.
  };

  const handleSync = async (connector: CloudConnector) => {
    if (!connector.connectionId || selectedFiles.length === 0) return;

    setIsIngesting(true);

    try {
      const syncBody: {
        connection_id: string;
        max_files?: number;
        selected_files?: string[];
        settings?: IngestSettings;
      } = {
        connection_id: connector.connectionId,
        selected_files: selectedFiles.map((file) => file.id),
        settings: ingestSettings,
      };

      const response = await fetch(`/api/connectors/${connector.type}/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(syncBody),
      });

      const result = await response.json();

      if (response.status === 201) {
        const taskIds = result.task_ids;
        if (taskIds && taskIds.length > 0) {
          const taskId = taskIds[0]; // Use the first task ID
          addTask(taskId);
          setCurrentSyncTaskId(taskId);
        }
      } else {
        console.error("Sync failed:", result.error);
      }
    } catch (error) {
      console.error("Sync error:", error);
      setIsIngesting(false);
    }
  };

  const getProviderDisplayName = () => {
    const nameMap: { [key: string]: string } = {
      google_drive: "Google Drive",
      onedrive: "OneDrive",
      sharepoint: "SharePoint",
    };
    return nameMap[provider] || provider;
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary mx-auto mb-4"></div>
          <p>Loading {getProviderDisplayName()} connector...</p>
        </div>
      </div>
    );
  }

  if (error || !connector) {
    return (
      <>
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>

        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">
              Provider Not Available
            </h2>
            <p className="text-muted-foreground mb-4">{error}</p>
            <Button onClick={() => router.push("/settings")}>
              Configure Connectors
            </Button>
          </div>
        </div>
      </>
    );
  }

  if (connector.status !== "connected") {
    return (
      <>
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>

        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-yellow-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">
              {connector.name} Not Connected
            </h2>
            <p className="text-muted-foreground mb-4">
              You need to connect your {connector.name} account before you can
              select files.
            </p>
            <Button onClick={() => router.push("/settings")}>
              Connect {connector.name}
            </Button>
          </div>
        </div>
      </>
    );
  }

  if (!connector.hasAccessToken) {
    return (
      <>
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={() => router.back()}
            className="mb-4"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </div>

        <div className="flex items-center justify-center py-12">
          <div className="text-center max-w-md">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">
              Access Token Required
            </h2>
            <p className="text-muted-foreground mb-4">
              {connector.accessTokenError ||
                `Unable to get access token for ${connector.name}. Try reconnecting your account.`}
            </p>
            <Button onClick={() => router.push("/settings")}>
              Reconnect {connector.name}
            </Button>
          </div>
        </div>
      </>
    );
  }

  const hasSelectedFiles = selectedFiles.length > 0;

  return (
    <>
      <div className="mb-8 flex gap-2 items-center">
        <Button variant="ghost" onClick={() => router.back()} size="icon">
          <ArrowLeft size={18} />
        </Button>
        <h2 className="text-xl text-[18px] font-semibold">
          Add from {getProviderDisplayName()}
        </h2>
      </div>

      <div className="max-w-3xl mx-auto">
        <UnifiedCloudPicker
          provider={
            connector.type as "google_drive" | "onedrive" | "sharepoint"
          }
          onFileSelected={handleFileSelected}
          selectedFiles={selectedFiles}
          isAuthenticated={true}
          isIngesting={isIngesting}
          accessToken={accessToken || undefined}
          clientId={connector.clientId}
          onSettingsChange={setIngestSettings}
        />
      </div>

      <div className="max-w-3xl mx-auto mt-6 sticky bottom-0 left-0 right-0 pb-6 bg-background pt-4">
        <div className="flex justify-between gap-3 mb-4">
          <Button
            variant="ghost"
            className="border bg-transparent border-border rounded-lg text-secondary-foreground"
            onClick={() => router.back()}
          >
            Back
          </Button>
          <Tooltip>
            <TooltipTrigger>
              <Button
                className="bg-foreground text-background hover:bg-foreground/90 font-semibold"
                variant={!hasSelectedFiles ? "secondary" : undefined}
                onClick={() => handleSync(connector)}
                loading={isIngesting}
                disabled={!hasSelectedFiles || isIngesting}
              >
                {hasSelectedFiles ? (
                  <>
                    Ingest {selectedFiles.length} item
                    {selectedFiles.length > 1 ? "s" : ""}
                  </>
                ) : (
                  <>Ingest selected items</>
                )}
              </Button>
            </TooltipTrigger>
            {!hasSelectedFiles ? (
              <TooltipContent side="left">
                Select at least one item before ingesting
              </TooltipContent>
            ) : null}
          </Tooltip>
        </div>
      </div>
    </>
  );
}
