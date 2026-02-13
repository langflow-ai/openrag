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

import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { useGetConnectorsQuery } from "@/app/api/queries/useGetConnectorsQuery";
import { useGetConnectorTokenQuery } from "@/app/api/queries/useGetConnectorTokenQuery";

// CloudFile interface is now imported from the unified cloud picker

export default function UploadProviderPage() {
  const params = useParams();
  const router = useRouter();
  const provider = params.provider as string;
  const { addTask, tasks } = useTask();

  const { data: connectors = [], isLoading: connectorsLoading, error: connectorsError } = useGetConnectorsQuery();
  const connector = connectors.find((c) => c.type === provider);

  const { data: tokenData, isLoading: tokenLoading } = useGetConnectorTokenQuery(
    {
      connectorType: provider,
      connectionId: connector?.connectionId,
      resource:
        provider === "sharepoint" ? (connector?.baseUrl as string) : undefined,
    },
    {
      enabled: !!connector && connector.status === "connected",
    },
  );

  const syncMutation = useSyncConnector();

  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
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

  const accessToken = tokenData?.access_token || null;
  const isLoading = connectorsLoading || tokenLoading;
  const isIngesting = syncMutation.isPending;

  // Error handling
  const error = connectorsError
    ? (connectorsError as Error).message
    : !connector && !connectorsLoading
      ? `Cloud provider "${provider}" is not available or configured.`
      : null;


  const handleFileSelected = (files: CloudFile[]) => {
    setSelectedFiles(files);
    console.log(`Selected ${files.length} item(s) from ${provider}:`, files);
    // You can add additional handling here like triggering sync, etc.
  };

  const handleSync = async (connector: any) => {
    if (!connector.connectionId || selectedFiles.length === 0) return;

    syncMutation.mutate(
      {
        connectorType: connector.type,
        body: {
          connection_id: connector.connectionId,
          selected_files: selectedFiles.map((file) => ({
            id: file.id,
            name: file.name,
            mimeType: file.mimeType,
            downloadUrl: file.downloadUrl,
            size: file.size,
          })),
          settings: ingestSettings,
        },
      },
      {
        onSuccess: (result) => {
          const taskIds = result.task_ids;
          if (taskIds && taskIds.length > 0) {
            const taskId = taskIds[0]; // Use the first task ID
            addTask(taskId);
            setCurrentSyncTaskId(taskId);
            // Redirect to knowledge page already to show the syncing document
            router.push("/knowledge");
          }
        },
      },
    );
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

  if (!accessToken) {
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
              Unable to get access token for {connector.name}. Try reconnecting your account.
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
          baseUrl={connector.baseUrl}
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
            <TooltipTrigger asChild>
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
