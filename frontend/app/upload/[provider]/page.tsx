"use client";

import { AlertCircle, ArrowLeft } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { useGetConnectorsQuery } from "@/app/api/queries/useGetConnectorsQuery";
import { useGetConnectorTokenQuery } from "@/app/api/queries/useGetConnectorTokenQuery";
import { type CloudFile, UnifiedCloudPicker } from "@/components/cloud-picker";
import { getIngestChunkSettingsError } from "@/components/cloud-picker/types";
import { DuplicateHandlingDialog } from "@/components/duplicate-handling-dialog";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTask } from "@/contexts/task-context";
import { useSessionIngestSettings } from "@/hooks/useSessionIngestSettings";
import { getConnectorDescriptor } from "@/lib/connectors/registry";

// CloudFile interface is now imported from the unified cloud picker

export default function UploadProviderPage() {
  const params = useParams();
  const router = useRouter();
  const provider = params.provider as string;
  const { addTask } = useTask();

  const {
    data: connectors = [],
    isLoading: connectorsLoading,
    error: connectorsError,
  } = useGetConnectorsQuery();
  const connector = connectors.find((c) => c.type === provider);
  const descriptor = getConnectorDescriptor(provider);
  const isDirectSyncProvider = descriptor?.kind === "bucket";

  const { data: tokenData, isLoading: tokenLoading } =
    useGetConnectorTokenQuery(
      {
        connectorType: provider,
        connectionId: connector?.connectionId,
        resource:
          provider === "sharepoint"
            ? (connector?.baseUrl as string)
            : undefined,
      },
      {
        // Bucket-kind connectors sync entire buckets and don't use OAuth tokens.
        enabled:
          !!connector &&
          connector.status === "connected" &&
          !isDirectSyncProvider,
      },
    );

  const syncMutation = useSyncConnector();

  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
  const [ingestSettings, setIngestSettings] = useSessionIngestSettings();
  const [isCheckingDuplicates, setIsCheckingDuplicates] = useState(false);
  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [pendingSync, setPendingSync] = useState<{
    connector: { connectionId?: string; type: string };
    allFiles: CloudFile[];
    nonDuplicateFiles: CloudFile[];
    duplicateNames: string[];
  } | null>(null);
  const isOverwriteConfirmedRef = useRef(false);

  const accessToken = tokenData?.access_token || null;
  const isLoading =
    connectorsLoading || (!isDirectSyncProvider && tokenLoading);
  const isIngesting = syncMutation.isPending;

  // Error handling
  const error = connectorsError
    ? (connectorsError as Error).message
    : !connector && !connectorsLoading
      ? `Cloud provider "${provider}" is not available or configured.`
      : null;

  const handleFileSelected = (files: CloudFile[]) => {
    setSelectedFiles(files);
  };

  const submitSync = (
    connector: { connectionId?: string; type: string },
    files: CloudFile[],
    replaceDuplicates: boolean,
  ) => {
    syncMutation.mutate(
      {
        connectorType: connector.type,
        body: {
          connection_id: connector.connectionId,
          selected_files: files.map((file) => ({
            id: file.id,
            name: file.name,
            mimeType: file.mimeType,
            downloadUrl: file.downloadUrl,
            size: file.size,
            isFolder: file.isFolder,
          })),
          settings: ingestSettings,
          replace_duplicates: replaceDuplicates,
        },
      },
      {
        onSuccess: (result) => {
          const taskIds = result.task_ids;
          if (taskIds && taskIds.length > 0) {
            addTask(taskIds[0]);
            router.push("/knowledge");
          }
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : "Sync failed");
        },
      },
    );
  };

  const getProviderDisplayName = () => descriptor?.name ?? provider;

  const handleSync = async (connector: {
    connectionId?: string;
    type: string;
  }) => {
    if (!connector.connectionId || selectedFiles.length === 0) return;

    const chunkErr = getIngestChunkSettingsError(ingestSettings);
    if (chunkErr) {
      toast.error("Could not start ingest", { description: chunkErr });
      return;
    }

    setIsCheckingDuplicates(true);
    try {
      const checkResponse = await fetch(
        `/api/connectors/${connector.type}/check-duplicates`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            connection_id: connector.connectionId,
            selected_files: selectedFiles.map((file) => ({
              id: file.id,
              name: file.name,
              mimeType: file.mimeType,
              downloadUrl: file.downloadUrl,
              size: file.size,
              isFolder: file.isFolder,
            })),
          }),
        },
      );

      if (!checkResponse.ok) {
        throw new Error(`Duplicate check failed: ${checkResponse.statusText}`);
      }

      const checkData = await checkResponse.json();
      const duplicateNames = checkData.duplicate_names || [];
      const totalFiles = checkData.total_files || 0;

      if (duplicateNames.length === 0) {
        submitSync(connector, selectedFiles, false);
        return;
      }

      // If all files are duplicates, we set nonDuplicateFiles to empty so it toasts "Nothing was synced" on skip
      const isAllDuplicate = duplicateNames.length === totalFiles;
      const nonDuplicateFiles = isAllDuplicate ? [] : selectedFiles;

      setPendingSync({
        connector,
        allFiles: selectedFiles,
        nonDuplicateFiles,
        duplicateNames,
      });
      setDuplicateDialogOpen(true);
    } catch (err) {
      console.error("[Connector Sync] Duplicate check failed:", err);
      // Fallback: proceed without overwrite
      submitSync(connector, selectedFiles, false);
    } finally {
      setIsCheckingDuplicates(false);
    }
  };

  const handleOverwriteDuplicates = () => {
    if (!pendingSync) return;
    isOverwriteConfirmedRef.current = true;
    const { connector, allFiles } = pendingSync;
    submitSync(connector, allFiles, true);
    setPendingSync(null);
  };

  const handleDuplicateDialogOpenChange = (open: boolean) => {
    if (!open && pendingSync) {
      if (isOverwriteConfirmedRef.current) {
        // Overwrite already submitted in handleOverwriteDuplicates; this close
        // event fires immediately after and would otherwise re-enter the
        // "skip duplicates" branch.
        isOverwriteConfirmedRef.current = false;
      } else {
        const { connector, nonDuplicateFiles, duplicateNames } = pendingSync;
        if (nonDuplicateFiles.length > 0) {
          submitSync(connector, nonDuplicateFiles, false);
        } else {
          toast.info(
            `All ${duplicateNames.length} selected file(s) already exist. Nothing was synced.`,
          );
        }
      }
      setPendingSync(null);
    }
    setDuplicateDialogOpen(open);
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

  // Bucket-kind connectors render their own bucket list view.
  if (
    isDirectSyncProvider &&
    connector.status === "connected" &&
    descriptor?.BucketView
  ) {
    const BucketView = descriptor.BucketView;
    return (
      <BucketView
        connector={connector}
        syncMutation={syncMutation}
        addTask={addTask}
        onBack={() => router.back()}
        onDone={() => router.push("/knowledge")}
      />
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
              Unable to get access token for {connector.name}. Try reconnecting
              your account.
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
          ingestSettings={ingestSettings}
          onIngestSettingsChange={setIngestSettings}
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
                loading={isIngesting || isCheckingDuplicates}
                disabled={
                  !hasSelectedFiles || isIngesting || isCheckingDuplicates
                }
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

      <DuplicateHandlingDialog
        open={duplicateDialogOpen}
        onOpenChange={handleDuplicateDialogOpenChange}
        onOverwrite={handleOverwriteDuplicates}
        isLoading={isIngesting}
        duplicateNames={pendingSync?.duplicateNames}
      />
    </>
  );
}
