"use client";

import { Check, Download, Loader2, RefreshCw, Search } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import {
  type RemoteFile,
  useBrowseConnectionFiles,
} from "@/app/api/queries/useBrowseConnectionFiles";
import type { IngestSettings } from "@/components/cloud-picker/types";
import { formatFileSize } from "@/lib/file-format";
import { DuplicateHandlingDialog } from "./duplicate-handling-dialog";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { ScrollArea } from "./ui/scroll-area";

interface SyncFilePayload {
  id: string;
  name: string;
  mimeType: string;
  size?: number;
}

interface FileBrowserDuplicateCheckResponse {
  duplicate_names?: string[];
  duplicate_count?: number;
  non_duplicate_files?: SyncFilePayload[];
}

interface FileBrowserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectorType: string;
  connectionId: string;
  buckets?: string[];
  onIngestSuccess?: (result: { task_ids?: string[]; message?: string }) => void;
  /** When true, apply the "Make documents available to all users" setting from `ingestSettings`. */
  showShared?: boolean;
  /** Ingest settings (embedding model, chunking, OCR, shared toggle) configured on the parent screen. */
  ingestSettings?: IngestSettings;
}

export function FileBrowserDialog({
  open,
  onOpenChange,
  connectorType,
  connectionId,
  buckets,
  onIngestSuccess,
  showShared,
  ingestSettings,
}: FileBrowserDialogProps) {
  const [search, setSearch] = useState("");
  const [selectedBucket, setSelectedBucket] = useState<string | undefined>(
    buckets?.[0],
  );
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(
    new Set(),
  );

  const syncMutation = useSyncConnector();

  // The bucket's file set is fetched once per open (search is NOT sent to the
  // backend — its server-side filter just post-filters this same capped list,
  // so re-fetching per keystroke only adds latency and remounts the loading
  // state, making the table jump). We filter the cached list in-memory instead.
  const { data, isLoading, error } = useBrowseConnectionFiles(
    {
      connectorType,
      connectionId,
      bucket: selectedBucket,
      maxFiles: 500,
    },
    { enabled: open },
  );

  const allFiles = useMemo(() => data?.files ?? [], [data]);

  const files = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q
      ? allFiles.filter((f) => f.name.toLowerCase().includes(q))
      : allFiles;
  }, [allFiles, search]);

  // Selectable files within the current (filtered) view — drives "Select all".
  // Already-ingested files are selectable too (re-checking one is an explicit
  // request to re-ingest it — handleIngest routes through the duplicate-check
  // confirmation flow before overwriting).
  const visibleSelectable = files;

  const allVisibleSelected =
    visibleSelectable.length > 0 &&
    visibleSelectable.every((f) => selectedFileIds.has(f.id));

  const toggleFile = useCallback((fileId: string) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      const allSelected =
        visibleSelectable.length > 0 &&
        visibleSelectable.every((f) => next.has(f.id));
      for (const f of visibleSelectable) {
        if (allSelected) {
          next.delete(f.id);
        } else {
          next.add(f.id);
        }
      }
      return next;
    });
  }, [visibleSelectable]);

  // Resolve selections against the full fetched set so a selection survives
  // filtering (a selected file hidden by the search box is still ingested).
  const selectedFiles = useMemo(
    () => allFiles.filter((f) => selectedFileIds.has(f.id)),
    [allFiles, selectedFileIds],
  );

  const [isCheckingDuplicates, setIsCheckingDuplicates] = useState(false);
  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [pendingSync, setPendingSync] = useState<{
    allFiles: SyncFilePayload[];
    nonDuplicateFiles: SyncFilePayload[];
    duplicateNames: string[];
    duplicateCount: number;
  } | null>(null);
  const isOverwriteConfirmedRef = useRef(false);

  const submitSync = useCallback(
    async (syncFiles: SyncFilePayload[], replaceDuplicates: boolean) => {
      try {
        const result = await syncMutation.mutateAsync({
          connectorType,
          body: {
            selected_files: syncFiles,
            settings: ingestSettings,
            shared: showShared ? (ingestSettings?.shared ?? false) : undefined,
            replace_duplicates: replaceDuplicates,
          },
        });

        toast.success("Ingestion started", {
          description: `${syncFiles.length} file(s) queued for ingestion.`,
        });

        setSelectedFileIds(new Set());
        onOpenChange(false);
        onIngestSuccess?.(result);
      } catch (err) {
        toast.error("Ingestion failed", {
          description: err instanceof Error ? err.message : "Unknown error",
        });
      }
    },
    [
      connectorType,
      syncMutation,
      onOpenChange,
      onIngestSuccess,
      showShared,
      ingestSettings,
    ],
  );

  const handleIngest = useCallback(async () => {
    if (selectedFiles.length === 0) return;

    const filesPayload: SyncFilePayload[] = selectedFiles.map((f) => ({
      id: f.id,
      name: f.name,
      mimeType: "",
      size: f.size,
    }));

    // If any selected file is a stale re-ingest, default to replacing the
    // indexed copy so the newer version overwrites the old chunks even if
    // the duplicate check below is skipped (network error) or doesn't flag
    // it. New files are unaffected by this flag.
    const hasStale = selectedFiles.some((f) => f.is_stale);

    setIsCheckingDuplicates(true);
    try {
      const checkResponse = await fetch(
        `/api/connectors/${connectorType}/check-duplicates`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            connection_id: connectionId,
            selected_files: filesPayload,
          }),
        },
      );

      if (!checkResponse.ok) {
        throw new Error(`Duplicate check failed: ${checkResponse.statusText}`);
      }

      const checkData =
        (await checkResponse.json()) as FileBrowserDuplicateCheckResponse;
      const duplicateNames = checkData.duplicate_names || [];
      const duplicateCount =
        typeof checkData.duplicate_count === "number"
          ? checkData.duplicate_count
          : duplicateNames.length;

      if (duplicateCount === 0) {
        await submitSync(filesPayload, hasStale);
        return;
      }

      setPendingSync({
        allFiles: filesPayload,
        nonDuplicateFiles: checkData.non_duplicate_files || [],
        duplicateNames,
        duplicateCount,
      });
      setDuplicateDialogOpen(true);
    } catch (err) {
      console.error("[File Browser] Duplicate check failed:", err);
      // Fallback: proceed without overwrite (backend will still skip
      // exact-duplicate filenames on its own), unless we already know some
      // selected files are stale re-ingests.
      await submitSync(filesPayload, hasStale);
    } finally {
      setIsCheckingDuplicates(false);
    }
  }, [selectedFiles, connectorType, connectionId, submitSync]);

  const handleOverwriteDuplicates = () => {
    if (!pendingSync) return;
    isOverwriteConfirmedRef.current = true;
    submitSync(pendingSync.allFiles, true);
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
        const { nonDuplicateFiles, duplicateCount } = pendingSync;
        if (nonDuplicateFiles.length > 0) {
          submitSync(nonDuplicateFiles, false);
        } else {
          toast.info(
            `All ${duplicateCount} selected file(s) already exist. Nothing was synced.`,
          );
        }
      }
      setPendingSync(null);
    }
    setDuplicateDialogOpen(open);
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Browse Files</DialogTitle>
            <DialogDescription>
              Select files to ingest from your {connectorType.replace("_", " ")}{" "}
              connection.
              {data && (
                <span className="ml-1">
                  {data.total_ingested} of {data.total_remote} file(s) already
                  ingested.
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="flex gap-2 items-center">
            {buckets && buckets.length > 1 && (
              <select
                className="border rounded px-2 py-1.5 text-sm bg-background"
                value={selectedBucket || ""}
                onChange={(e) => {
                  setSelectedBucket(e.target.value || undefined);
                  setSelectedFileIds(new Set());
                }}
              >
                {buckets.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            )}
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search files..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          <ScrollArea className="flex-1 min-h-0 max-h-[400px] border rounded">
            {isLoading ? (
              <div className="flex items-center justify-center p-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                <span className="ml-2 text-muted-foreground">
                  Loading files...
                </span>
              </div>
            ) : error ? (
              <div className="p-4 text-destructive text-sm">
                Failed to load files:{" "}
                {error instanceof Error ? error.message : "Unknown error"}
              </div>
            ) : files.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground text-sm">
                {search.trim() && allFiles.length > 0
                  ? "No files match your search."
                  : "No files found."}
              </div>
            ) : (
              <div className="divide-y">
                {visibleSelectable.length > 0 && (
                  <div className="px-3 py-2 bg-muted/50 flex items-center gap-2 sticky top-0">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleAll}
                      className="h-4 w-4 rounded border border-input"
                    />
                    <span className="text-xs text-muted-foreground">
                      {selectedFileIds.size > 0
                        ? `${selectedFileIds.size} selected`
                        : `Select all (${visibleSelectable.length})`}
                    </span>
                  </div>
                )}
                {files.map((file) => (
                  <FileRow
                    key={file.id}
                    file={file}
                    selected={selectedFileIds.has(file.id)}
                    onToggle={() => toggleFile(file.id)}
                  />
                ))}
              </div>
            )}
          </ScrollArea>

          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleIngest}
              disabled={
                selectedFiles.length === 0 ||
                syncMutation.isPending ||
                isCheckingDuplicates
              }
            >
              {syncMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Ingesting...
                </>
              ) : isCheckingDuplicates ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Checking...
                </>
              ) : (
                <>
                  <Download className="h-4 w-4 mr-2" />
                  Ingest{" "}
                  {selectedFiles.length > 0
                    ? `${selectedFiles.length} file(s)`
                    : "selected"}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DuplicateHandlingDialog
        open={duplicateDialogOpen}
        onOpenChange={handleDuplicateDialogOpenChange}
        onOverwrite={handleOverwriteDuplicates}
        isLoading={syncMutation.isPending}
        duplicateNames={pendingSync?.duplicateNames}
        duplicateCount={pendingSync?.duplicateCount}
      />
    </>
  );
}

function FileRow({
  file,
  selected,
  onToggle,
}: {
  file: RemoteFile;
  selected: boolean;
  onToggle: () => void;
}) {
  // The blob/object key is the full path within the bucket/container (e.g.
  // "invoices/2024/report.pdf"); file.name is only the basename. Surfacing the
  // directory portion disambiguates same-named files living under different
  // prefixes (e.g. 2024/report.pdf vs 2025/report.pdf), which otherwise render
  // identically. Empty for top-level/flat blobs, so flat listings are unchanged.
  const dir = useMemo(() => {
    const key = file.key ?? "";
    const idx = key.lastIndexOf("/");
    return idx >= 0 ? key.slice(0, idx + 1) : "";
  }, [file.key]);

  return (
    <label className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-muted/30 transition-colors">
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="h-4 w-4 rounded border border-input"
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate font-medium">{file.name}</div>
        {dir && (
          <div
            className="text-xs text-muted-foreground truncate"
            title={file.key}
          >
            {dir}
          </div>
        )}
        <div className="text-xs text-muted-foreground flex gap-2">
          {file.bucket && <span>{file.bucket}</span>}
          <span>{formatFileSize(file.size)}</span>
          {file.modified_time && (
            <span>{new Date(file.modified_time).toLocaleDateString()}</span>
          )}
        </div>
      </div>
      {file.is_stale ? (
        <Badge variant="outline" className="text-xs flex-shrink-0">
          <RefreshCw className="h-3 w-3 mr-1" />
          Update available
        </Badge>
      ) : (
        file.is_ingested && (
          <Badge variant="secondary" className="text-xs flex-shrink-0">
            <Check className="h-3 w-3 mr-1" />
            Ingested
          </Badge>
        )
      )}
    </label>
  );
}
