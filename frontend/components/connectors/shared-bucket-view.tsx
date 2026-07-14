"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileSearch, FolderOpen, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import type { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { IngestSettings } from "@/components/cloud-picker/ingest-settings";
import { getIngestChunkSettingsError } from "@/components/cloud-picker/types";
import { FileBrowserDialog } from "@/components/file-browser-dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import { useSessionIngestSettings } from "@/hooks/useSessionIngestSettings";
import { trackProcessFailure, trackStartProcess } from "@/lib/analytics";

export interface SharedBucketViewProps {
  connector: any;
  buckets: Array<{ name: string; ingested_count: number }> | undefined;
  isLoading: boolean;
  bucketsError?: Error | null;
  onRefetch: () => void;
  invalidateQueryKey: readonly unknown[];
  syncMutation: ReturnType<typeof useSyncConnector>;
  addTask: (
    id: string,
    options?: { connectorType?: string; source?: string },
  ) => void;
  onBack: () => void;
  onDone: () => void;
  /** When true, show the "Make documents available to all users" toggle. COS ingestion only. */
  showShared?: boolean;
  /** Buckets to pre-select once `buckets` has loaded, e.g. from saved connector defaults. */
  initialSelectedBuckets?: string[];
}

export function SharedBucketView({
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
  showShared = false,
  initialSelectedBuckets,
}: SharedBucketViewProps) {
  const queryClient = useQueryClient();
  const { isAuthenticated, isNoAuthMode } = useAuth();
  const { data: apiSettings } = useGetSettingsQuery({
    enabled: isAuthenticated || isNoAuthMode,
  });
  const showIngestSettings =
    apiSettings?.show_provider_ingest_settings ?? false;

  const [selectedBuckets, setSelectedBuckets] = useState<Set<string>>(
    new Set(),
  );
  const hasAppliedInitial = useRef(false);
  const [ingestSettings, setIngestSettings] = useSessionIngestSettings();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [browseDialogBucket, setBrowseDialogBucket] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (
      !hasAppliedInitial.current &&
      buckets?.length &&
      initialSelectedBuckets?.length
    ) {
      hasAppliedInitial.current = true;
      if (selectedBuckets.size === 0) {
        const valid = initialSelectedBuckets.filter((name) =>
          buckets.some((b) => b.name === name),
        );
        if (valid.length) {
          setSelectedBuckets(new Set(valid));
        }
      }
    }
  }, [buckets, initialSelectedBuckets, selectedBuckets.size]); // eslint-disable-line react-hooks/exhaustive-deps

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: invalidateQueryKey });
  };

  const trackIngestTasks = (taskIds?: string[]) => {
    for (const id of taskIds ?? []) {
      addTask(id, { connectorType: connector.type, source: "connector" });
    }
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
    const chunkErr = getIngestChunkSettingsError(ingestSettings);
    if (chunkErr) {
      toast.error("Could not start ingest", { description: chunkErr });
      return;
    }
    trackStartProcess({
      processType: "Ingestion",
      process: "Document Upload",
      category: "Knowledge",
      source: "connector",
      connector_type: connector.type,
      total_buckets: selectedBuckets.size,
    });
    syncMutation.mutate(
      {
        connectorType: connector.type,
        body: {
          connection_id: connector.connectionId!,
          selected_files: [],
          bucket_filter: Array.from(selectedBuckets),
          settings: ingestSettings,
          shared: showShared ? (ingestSettings.shared ?? false) : undefined,
        },
      },
      {
        onSuccess: (result) => {
          invalidate();
          if (result.task_ids?.length) {
            // The container path may return two tasks (new files + changed files);
            // track them all.
            trackIngestTasks(result.task_ids);
            onDone();
          } else {
            toast.info(
              result.message ?? "No files found in the selected buckets.",
            );
          }
        },
        onError: (err) => {
          trackProcessFailure({
            processType: "Ingestion",
            process: "Document Upload",
            category: "Knowledge",
            source: "connector",
            connector_type: connector.type,
            resultValue: err instanceof Error ? err.message : "Sync failed",
          });
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
                  role="checkbox"
                  aria-checked={isSelected}
                  aria-label={bucket.name}
                  tabIndex={0}
                  className="flex items-center gap-[18px] px-4 py-3 cursor-pointer"
                  onClick={() => toggleBucket(bucket.name)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleBucket(bucket.name);
                    }
                  }}
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
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                        setBrowseDialogBucket(bucket.name);
                      }}
                    >
                      <FileSearch size={14} className="mr-1.5" />
                      Browse Files
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {showIngestSettings && (
          <IngestSettings
            isOpen={isSettingsOpen}
            onOpenChange={setIsSettingsOpen}
            settings={ingestSettings}
            onSettingsChange={setIngestSettings}
            showShared={showShared}
          />
        )}
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

      {connector.connectionId && browseDialogBucket && (
        <FileBrowserDialog
          open
          onOpenChange={(open) => {
            if (!open) setBrowseDialogBucket(null);
          }}
          connectorType={connector.type}
          connectionId={connector.connectionId}
          buckets={[browseDialogBucket]}
          onIngestSuccess={(result) => {
            invalidate();
            if (result.task_ids?.length) {
              trackIngestTasks(result.task_ids);
              onDone();
            } else {
              toast.info(
                result.message ?? "No files were queued for ingestion.",
              );
            }
          }}
        />
      )}
    </>
  );
}
