"use client";

import { Check, Download, Loader2, Search } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";
import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import {
  type RemoteFile,
  useBrowseConnectionFiles,
} from "@/app/api/queries/useBrowseConnectionFiles";
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

interface FileBrowserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectorType: string;
  connectionId: string;
  buckets?: string[];
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function FileBrowserDialog({
  open,
  onOpenChange,
  connectorType,
  connectionId,
  buckets,
}: FileBrowserDialogProps) {
  const [search, setSearch] = useState("");
  const [selectedBucket, setSelectedBucket] = useState<string | undefined>(
    buckets?.[0],
  );
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(
    new Set(),
  );

  const syncMutation = useSyncConnector();

  const { data, isLoading, error } = useBrowseConnectionFiles(
    {
      connectorType,
      connectionId,
      bucket: selectedBucket,
      search: search || undefined,
      maxFiles: 500,
    },
    { enabled: open },
  );

  const files = data?.files ?? [];

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
    const unIngestedFiles = files.filter((f) => !f.is_ingested);
    if (selectedFileIds.size === unIngestedFiles.length) {
      setSelectedFileIds(new Set());
    } else {
      setSelectedFileIds(new Set(unIngestedFiles.map((f) => f.id)));
    }
  }, [files, selectedFileIds.size]);

  const selectedFiles = useMemo(
    () => files.filter((f) => selectedFileIds.has(f.id)),
    [files, selectedFileIds],
  );

  const handleIngest = useCallback(async () => {
    if (selectedFiles.length === 0) return;

    try {
      await syncMutation.mutateAsync({
        connectorType,
        body: {
          selected_files: selectedFiles.map((f) => ({
            id: f.id,
            name: f.name,
            mimeType: "",
            size: f.size,
          })),
        },
      });

      toast.success("Ingestion started", {
        description: `${selectedFiles.length} file(s) queued for ingestion.`,
      });

      setSelectedFileIds(new Set());
      onOpenChange(false);
    } catch (err) {
      toast.error("Ingestion failed", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    }
  }, [selectedFiles, connectorType, syncMutation, onOpenChange]);

  const unIngestedCount = files.filter((f) => !f.is_ingested).length;

  return (
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
              No files found.
            </div>
          ) : (
            <div className="divide-y">
              {unIngestedCount > 0 && (
                <div className="px-3 py-2 bg-muted/50 flex items-center gap-2 sticky top-0">
                  <input
                    type="checkbox"
                    checked={
                      selectedFileIds.size === unIngestedCount &&
                      unIngestedCount > 0
                    }
                    onChange={toggleAll}
                    className="h-4 w-4 rounded border-border"
                  />
                  <span className="text-xs text-muted-foreground">
                    {selectedFileIds.size > 0
                      ? `${selectedFileIds.size} selected`
                      : `Select all (${unIngestedCount})`}
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
            disabled={selectedFiles.length === 0 || syncMutation.isPending}
          >
            {syncMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Ingesting...
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
  return (
    <label
      className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-muted/30 transition-colors ${
        file.is_ingested ? "opacity-60" : ""
      }`}
    >
      <input
        type="checkbox"
        checked={selected || file.is_ingested}
        disabled={file.is_ingested}
        onChange={onToggle}
        className="h-4 w-4 rounded border-border"
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate font-medium">{file.name}</div>
        <div className="text-xs text-muted-foreground flex gap-2">
          {file.bucket && <span>{file.bucket}</span>}
          <span>{formatFileSize(file.size)}</span>
          {file.modified_time && (
            <span>{new Date(file.modified_time).toLocaleDateString()}</span>
          )}
        </div>
      </div>
      {file.is_ingested && (
        <Badge variant="secondary" className="text-xs flex-shrink-0">
          <Check className="h-3 w-3 mr-1" />
          Ingested
        </Badge>
      )}
    </label>
  );
}
