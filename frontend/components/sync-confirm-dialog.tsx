"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import type React from "react";
import type { OrphanFile } from "@/app/api/mutations/useSyncConnector";
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
import { ScrollArea } from "./ui/scroll-area";
import { Separator } from "./ui/separator";

const CONNECTOR_DISPLAY_NAMES: Record<string, string> = {
  google_drive: "Google Drive",
  onedrive: "OneDrive",
  sharepoint: "SharePoint",
  ibm_cos: "IBM Cloud Object Storage",
  aws_s3: "Amazon S3",
};

const formatConnectorLabel = (type: string): string =>
  CONNECTOR_DISPLAY_NAMES[type] ?? type;

interface SyncConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void | Promise<void>;
  /** True while the preview request is still in flight. */
  isLoading?: boolean;
  /** True after Confirm is clicked, while the actual sync request runs. */
  isSyncing?: boolean;
  /** Single-connector mode: the orphan list for this connector. */
  orphans?: OrphanFile[];
  /** Sync-all mode: orphans grouped by connector_type. */
  orphansByType?: Record<string, OrphanFile[]>;
  /** Per-connector availability flag — false means orphan detection couldn't
   * complete safely (e.g. unauthenticated connection). */
  orphansAvailableByType?: Record<string, boolean>;
  /** Single-connector mode: total files about to be re-synced. */
  syncedCount?: number;
  /** Sync-all mode: per-connector synced counts. */
  syncedCountByType?: Record<string, number>;
  /** Single-connector mode: connector type for the title (e.g. "sharepoint"). */
  connectorType?: string;
  /** When true, render the sync-all view (groups by connector_type). */
  isSyncAll?: boolean;
}

export const SyncConfirmDialog: React.FC<SyncConfirmDialogProps> = ({
  open,
  onOpenChange,
  onConfirm,
  isLoading = false,
  isSyncing = false,
  orphans,
  orphansByType,
  orphansAvailableByType,
  syncedCount,
  syncedCountByType,
  connectorType,
  isSyncAll = false,
}) => {
  const handleConfirm = async () => {
    await onConfirm();
    onOpenChange(false);
  };

  const totalOrphans = isSyncAll
    ? Object.values(orphansByType ?? {}).reduce(
        (sum, list) => sum + list.length,
        0,
      )
    : (orphans?.length ?? 0);

  const totalSynced = isSyncAll
    ? Object.values(syncedCountByType ?? {}).reduce((sum, n) => sum + n, 0)
    : (syncedCount ?? 0);

  const hasOrphans = totalOrphans > 0;
  const busy = isLoading || isSyncing;

  const title = isSyncAll ? "Sync all connectors" : "Confirm sync";

  let description: React.ReactNode;
  if (isLoading) {
    description = "Checking what will change…";
  } else if (hasOrphans) {
    description = (
      <>
        <span className="font-medium text-foreground">
          {totalOrphans} {totalOrphans === 1 ? "file" : "files"}
        </span>{" "}
        will be removed from your knowledge base because they no longer exist at
        the source. {totalSynced} {totalSynced === 1 ? "file" : "files"} will be
        re-synced. This can't be undone.
      </>
    );
  } else {
    description = (
      <>
        {totalSynced} {totalSynced === 1 ? "file" : "files"} will be re-synced.
        No files will be deleted.
      </>
    );
  }

  const renderOrphanList = (list: OrphanFile[]) => (
    <ul className="space-y-1 text-sm">
      {list.map((o) => (
        <li
          key={o.document_id}
          className="truncate text-muted-foreground"
          title={o.filename || o.document_id}
        >
          {o.filename || o.document_id}
        </li>
      ))}
    </ul>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <div className="flex items-center justify-between gap-2">
            <DialogTitle>
              {title}
              {!isSyncAll && connectorType ? (
                <span className="text-muted-foreground font-normal">
                  {" "}
                  · {formatConnectorLabel(connectorType)}
                </span>
              ) : null}
            </DialogTitle>
            {hasOrphans ? (
              <Badge
                variant="secondary"
                className="bg-accent-amber-foreground/15 text-accent-amber-foreground"
              >
                {totalOrphans} will be deleted
              </Badge>
            ) : null}
          </div>
          <DialogDescription className="pt-2 text-muted-foreground">
            {description}
          </DialogDescription>
        </DialogHeader>

        {hasOrphans ? (
          <div className="rounded-md border border-accent-amber-foreground/30 bg-accent-amber-foreground/5 p-3">
            <div className="flex items-center gap-2 mb-2 text-sm font-medium text-accent-amber-foreground">
              <AlertTriangle className="h-4 w-4" />
              Files to be deleted
            </div>
            <ScrollArea className="max-h-60">
              {isSyncAll ? (
                <div className="space-y-3 pr-2">
                  {Object.entries(orphansByType ?? {})
                    .filter(([, list]) => list.length > 0)
                    .map(([type, list], index, arr) => (
                      <div key={type}>
                        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-1">
                          {formatConnectorLabel(type)} ({list.length})
                        </div>
                        {renderOrphanList(list)}
                        {index < arr.length - 1 ? (
                          <Separator className="mt-3" />
                        ) : null}
                      </div>
                    ))}
                </div>
              ) : (
                <div className="pr-2">{renderOrphanList(orphans ?? [])}</div>
              )}
            </ScrollArea>
          </div>
        ) : null}

        {/* Surface "couldn't determine deletions" when strict gating aborted. */}
        {isSyncAll && orphansAvailableByType
          ? Object.entries(orphansAvailableByType)
              .filter(([, available]) => !available)
              .map(([type]) => (
                <div
                  key={type}
                  className="text-xs text-muted-foreground italic"
                >
                  Couldn't determine deletions for {formatConnectorLabel(type)}{" "}
                  (a connection may need re-authentication).
                </div>
              ))
          : null}

        <DialogFooter className="flex-row gap-2 justify-end">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={busy}
            size="sm"
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={handleConfirm}
            disabled={busy}
            className={
              hasOrphans
                ? "flex items-center gap-2 !bg-accent-amber-foreground hover:!bg-foreground text-primary-foreground"
                : "flex items-center gap-2"
            }
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {hasOrphans ? "Delete & sync" : "Confirm sync"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
