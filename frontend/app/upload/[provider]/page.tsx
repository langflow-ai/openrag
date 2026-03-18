"use client";

import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, FolderOpen, RefreshCw } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { useGetConnectorsQuery } from "@/app/api/queries/useGetConnectorsQuery";
import { useGetConnectorTokenQuery } from "@/app/api/queries/useGetConnectorTokenQuery";
import { useIBMCOSBucketStatusQuery } from "@/app/api/queries/useIBMCOSBucketStatusQuery";
import { useS3BucketStatusQuery } from "@/app/api/queries/useS3BucketStatusQuery";
import { type CloudFile, UnifiedCloudPicker } from "@/components/cloud-picker";
import { IngestSettings } from "@/components/cloud-picker/ingest-settings";
import type { IngestSettings as IngestSettingsType } from "@/components/cloud-picker/types";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTask } from "@/contexts/task-context";

// Connectors that sync entire buckets/repositories without a file picker
const DIRECT_SYNC_PROVIDERS = ["ibm_cos", "aws_s3"];

// ---------------------------------------------------------------------------
// Shared bucket view — used by both IBM COS and S3
// ---------------------------------------------------------------------------

function BucketView({
  connector,
  buckets,
  isLoading,
  bucketsError,
  onRefetch,
  invalidateQueryKey,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: {
  connector: any;
  buckets: Array<{ name: string; ingested_count: number }> | undefined;
  isLoading: boolean;
  bucketsError?: Error | null;
  onRefetch: () => void;
  invalidateQueryKey: readonly unknown[];
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [selectedBuckets, setSelectedBuckets] = useState<Set<string>>(
    new Set(),
  );
  const [ingestSettings, setIngestSettings] = useState<IngestSettingsType>({
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: "text-embedding-3-small",
  });
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: invalidateQueryKey });
  };

  const toggleBucket = (bucketName: string) => {
    setSelectedBuckets((prev) => {
      const next = new Set(prev);
      if (next.has(bucketName)) {
        next.delete(bucketName);
      } else {
        next.add(bucketName);
      }
      return next;
    });
  };

  const ingestSelected = () => {
    syncMutation.mutate(
      {
        connectorType: connector.type,
        body: {
          connection_id: connector.connectionId!,
          selected_files: [],
          bucket_filter: Array.from(selectedBuckets),
          settings: ingestSettings,
        },
      },
      {
        onSuccess: (result) => {
          invalidate();
          if (result.task_ids?.length) {
            addTask(result.task_ids[0]);
            onDone();
          } else {
            toast.info("No files found in the selected buckets.");
          }
        },
        onError: (err) => {
          toast.error(err instanceof Error ? err.message : "Sync failed");
        },
      },
    );
  };

  return (
    <>
      <div className="mb-8 flex gap-2 items-center">
        <Button variant="ghost" onClick={onBack} size="icon">
          <ArrowLeft size={18} />
        </Button>
        <h2 className="text-xl text-[18px] font-semibold">
          Add from {connector.name}
        </h2>
      </div>

      <div className="max-w-3xl mx-auto space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Select buckets to ingest.
          </p>
          <div className="flex items-center gap-2">
            {selectedBuckets.size > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSelectedBuckets(new Set())}
              >
                Deselect All
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setSelectedBuckets(new Set(buckets?.map((b) => b.name) ?? []))
              }
              disabled={isLoading || !buckets?.length}
            >
              Select All
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onRefetch}
              disabled={isLoading}
            >
              <RefreshCw
                size={14}
                className={isLoading ? "animate-spin" : ""}
              />
              Refresh Buckets
            </Button>
          </div>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-8">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
          </div>
        ) : bucketsError ? (
          <div className="rounded-lg border border-destructive/50 p-6 text-center text-destructive text-sm">
            {bucketsError.message ||
              "Failed to load buckets. Check your credentials and endpoint."}
          </div>
        ) : !buckets?.length ? (
          <div className="rounded-lg border p-6 text-center text-muted-foreground text-sm">
            No buckets found. Check your credentials and endpoint.
          </div>
        ) : (
          <div className="rounded-lg border divide-y">
            {buckets.map((bucket) => {
              const isSelected = selectedBuckets.has(bucket.name);
              return (
                <div
                  key={bucket.name}
                  className="flex items-center gap-[18px] px-4 py-3 cursor-pointer"
                  onClick={() => toggleBucket(bucket.name)}
                >
                  <div
                    className={`shrink-0 size-5 rounded-[6px] border-2 flex items-center justify-center transition-colors ${
                      isSelected
                        ? "bg-foreground border-foreground"
                        : "border-muted-foreground/60"
                    }`}
                  >
                    {isSelected && (
                      <svg
                        viewBox="0 0 12 12"
                        fill="none"
                        className="size-3 text-background"
                        stroke="currentColor"
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <polyline points="2,6 5,9 10,3" />
                      </svg>
                    )}
                  </div>
                  <div className="flex items-center gap-4 flex-1 min-w-0">
                    <div className="bg-white/5 rounded-[10px] shrink-0 size-10 flex items-center justify-center">
                      <FolderOpen size={20} className="text-muted-foreground" />
                    </div>
                    <div className="flex flex-col gap-1 min-w-0">
                      <p className="font-medium text-sm leading-6">
                        {bucket.name}
                      </p>
                      {bucket.ingested_count > 0 && (
                        <p className="text-xs text-muted-foreground">
                          {bucket.ingested_count} document
                          {bucket.ingested_count !== 1 ? "s" : ""} ingested
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <IngestSettings
          isOpen={isSettingsOpen}
          onOpenChange={setIsSettingsOpen}
          settings={ingestSettings}
          onSettingsChange={setIngestSettings}
        />
      </div>

      <div className="max-w-3xl mx-auto mt-6 sticky bottom-0 left-0 right-0 pb-6 bg-background pt-4">
        <div className="flex justify-between gap-3">
          <Button
            variant="ghost"
            className="border bg-transparent border-border rounded-lg text-secondary-foreground"
            onClick={onBack}
          >
            Back
          </Button>
          <Button
            className="bg-foreground text-background hover:bg-foreground/90 font-semibold"
            onClick={ingestSelected}
            disabled={syncMutation.isPending || selectedBuckets.size === 0}
            loading={syncMutation.isPending}
          >
            {syncMutation.isPending
              ? "Ingesting…"
              : selectedBuckets.size > 0
                ? `Ingest ${selectedBuckets.size} Bucket${selectedBuckets.size !== 1 ? "s" : ""}`
                : "Select Buckets to Ingest"}
          </Button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// IBM COS wrapper
// ---------------------------------------------------------------------------

function IBMCOSBucketView({
  connector,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: {
  connector: any;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const {
    data: buckets,
    isLoading,
    refetch,
  } = useIBMCOSBucketStatusQuery(connector.connectionId, { enabled: true });
  return (
    <BucketView
      connector={connector}
      buckets={buckets}
      isLoading={isLoading}
      onRefetch={refetch}
      invalidateQueryKey={["ibm-cos-bucket-status", connector.connectionId]}
      syncMutation={syncMutation}
      addTask={addTask}
      onBack={onBack}
      onDone={onDone}
    />
  );
}

// ---------------------------------------------------------------------------
// Amazon S3 wrapper
// ---------------------------------------------------------------------------

function S3BucketView({
  connector,
  syncMutation,
  addTask,
  onBack,
  onDone,
}: {
  connector: any;
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (id: string) => void;
  onBack: () => void;
  onDone: () => void;
}) {
  const {
    data: buckets,
    isLoading,
    error: bucketsError,
    refetch,
  } = useS3BucketStatusQuery(connector.connectionId, { enabled: true });
  return (
    <BucketView
      connector={connector}
      buckets={buckets}
      isLoading={isLoading}
      bucketsError={bucketsError as Error | null}
      onRefetch={refetch}
      invalidateQueryKey={["s3-bucket-status", connector.connectionId]}
      syncMutation={syncMutation}
      addTask={addTask}
      onBack={onBack}
      onDone={onDone}
    />
  );
}

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

  const isDirectSyncProvider = DIRECT_SYNC_PROVIDERS.includes(provider);

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
        // Direct-sync providers (e.g. IBM COS) don't use OAuth tokens
        enabled:
          !!connector &&
          connector.status === "connected" &&
          !isDirectSyncProvider,
      },
    );

  const syncMutation = useSyncConnector();

  const [selectedFiles, setSelectedFiles] = useState<CloudFile[]>([]);
  const [ingestSettings, setIngestSettings] = useState<IngestSettingsType>({
    chunkSize: 1000,
    chunkOverlap: 200,
    ocr: false,
    pictureDescriptions: false,
    embeddingModel: "text-embedding-3-small",
  });

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

  // Direct-sync providers show a bucket list with sync status.
  if (isDirectSyncProvider && connector.status === "connected") {
    if (provider === "aws_s3") {
      return (
        <S3BucketView
          connector={connector}
          syncMutation={syncMutation}
          addTask={addTask}
          onBack={() => router.back()}
          onDone={() => router.push("/knowledge")}
        />
      );
    }
    return (
      <IBMCOSBucketView
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
