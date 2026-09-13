"use client";

import { AlertTriangle, Check, Loader2, RefreshCw, Trash2 } from "lucide-react";
import type React from "react";
import type { OrphanFile } from "@/app/api/mutations/useSyncConnector";
import { getConnectorLabel } from "@/lib/connectors/registry";
import { summarizeSyncPreview } from "./sync-confirm-dialog-data";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
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

const formatConnectorLabel = (type: string): string =>
  getConnectorLabel(type) ?? type;

const pluralize = (n: number, singular: string, plural?: string): string =>
  `${n} ${n === 1 ? singular : (plural ?? `${singular}s`)}`;

/** Rough row-count above which the deletes ScrollArea (max-h-60 ≈ 240px) will
 * overflow and the user needs a scroll affordance. */
const SCROLL_HINT_THRESHOLD = 8;

interface SyncConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void | Promise<void>;
  /** True while the preview request is still in flight. */
  isLoading?: boolean;
  /** True after Confirm is clicked, while the actual sync request runs. */
  isSyncing?: boolean;
  /** Single-connector mode: deleted-at-source files for this connector.
   * "Orphans" = documents indexed locally that no longer exist at the source. */
  orphans?: OrphanFile[];
  /** Sync-all mode: orphans (deletions) grouped by connector_type. */
  orphansByType?: Record<string, OrphanFile[]>;
  /** Per-connector availability flag — false means orphan detection couldn't
   * complete safely (e.g. unauthenticated connection). */
  orphansAvailableByType?: Record<string, boolean>;
  /** Single-connector mode: files whose source copy changed and will be re-ingested. */
  updates?: OrphanFile[];
  /** Sync-all mode: changed files grouped by connector_type. */
  updatesByType?: Record<string, OrphanFile[]>;
  /** Per-connector flag — false means the connector can't predict updates (it
   * decides per file while ingesting), NOT that nothing will be updated. Those
   * connectors are reported as "re-checked" using their synced count. */
  updatesAvailableByType?: Record<string, boolean>;
  /** Single-connector mode: total files currently synced for this connector. */
  syncedCount?: number;
  /** Sync-all mode: per-connector synced totals. */
  syncedCountByType?: Record<string, number>;
  /** Single-connector mode: connector type for the title (e.g. "sharepoint"). */
  connectorType?: string;
  /** When true, render the sync-all view (groups by connector_type). */
  isSyncAll?: boolean;
}

const OrphanList = ({ list }: { list: OrphanFile[] }) => (
  <ul className="space-y-1 text-sm">
    {list.map((o) => (
      <li
        key={o.document_id}
        className="truncate"
        title={o.filename || o.document_id}
      >
        {o.filename || o.document_id}
      </li>
    ))}
  </ul>
);

const DeletesAlert = ({
  orphansByType,
  totalOrphans,
  isSyncAll,
}: {
  orphansByType: Record<string, OrphanFile[]>;
  totalOrphans: number;
  isSyncAll: boolean;
}) => {
  const entries = Object.entries(orphansByType);

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Removing
      </div>
      <Alert variant="destructive" className="bg-[#271919] text-[#ffced0]">
        <AlertTriangle className="size-5" />
        <AlertTitle>
          {pluralize(totalOrphans, "file")} will be deleted
        </AlertTitle>
        <AlertDescription className="col-start-2 block min-w-0 !text-[#ffced0]">
          <p>These files no longer exist at the source.</p>
          <ScrollArea className="mt-2 max-h-60 w-full">
            {isSyncAll ? (
              <div className="space-y-3 pr-2">
                {entries.map(([type, list], index) => (
                  <div key={type}>
                    <div className="text-xs font-semibold uppercase tracking-wide mb-1">
                      {formatConnectorLabel(type)} ({list.length})
                    </div>
                    <OrphanList list={list} />
                    {index < entries.length - 1 ? (
                      <Separator className="mt-3" />
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="pr-2">
                <OrphanList list={entries[0]?.[1] ?? []} />
              </div>
            )}
          </ScrollArea>
          {totalOrphans > SCROLL_HINT_THRESHOLD ? (
            <p className="mt-2 text-xs italic opacity-80">
              Scroll to review all {totalOrphans} files.
            </p>
          ) : null}
        </AlertDescription>
      </Alert>
    </div>
  );
};

const UnavailableAlert = ({ connectors }: { connectors: string[] }) => (
  <Alert>
    <AlertTriangle className="size-5" />
    <AlertTitle>Couldn&apos;t check for deletions</AlertTitle>
    <AlertDescription className="col-start-2 block min-w-0 [text-wrap:pretty]">
      <p>
        Files may be removed at the source without warning. Re-authenticate the
        affected connection and try again to see a full preview.
      </p>
      <ul className="mt-2 space-y-0.5">
        {connectors.map((type) => (
          <li key={type}>· {formatConnectorLabel(type)}</li>
        ))}
      </ul>
    </AlertDescription>
  </Alert>
);

const UpdatesAlert = ({
  updatesByType,
  totalUpdates,
  isSyncAll,
}: {
  updatesByType: Record<string, OrphanFile[]>;
  totalUpdates: number;
  isSyncAll: boolean;
}) => {
  const entries = Object.entries(updatesByType);

  return (
    <Alert>
      <RefreshCw className="size-5" />
      <AlertTitle>{pluralize(totalUpdates, "file")} will be updated</AlertTitle>
      <AlertDescription className="col-start-2 block min-w-0">
        <p>These files changed at the source since they were last ingested.</p>
        <ScrollArea className="mt-2 max-h-60 w-full">
          {isSyncAll && entries.length > 1 ? (
            <div className="space-y-3 pr-2">
              {entries.map(([type, list], index) => (
                <div key={type}>
                  <div className="text-xs font-semibold uppercase tracking-wide mb-1">
                    {formatConnectorLabel(type)} ({list.length})
                  </div>
                  <OrphanList list={list} />
                  {index < entries.length - 1 ? (
                    <Separator className="mt-3" />
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="pr-2">
              <OrphanList list={entries[0]?.[1] ?? []} />
            </div>
          )}
        </ScrollArea>
        {totalUpdates > SCROLL_HINT_THRESHOLD ? (
          <p className="mt-2 text-xs italic opacity-80">
            Scroll to review all {totalUpdates} files.
          </p>
        ) : null}
      </AlertDescription>
    </Alert>
  );
};

/** Connectors that re-read every file during sync and update the ones whose
 * content actually changed. The count can't be known before the sync runs, so
 * say that rather than showing a number that looks like a prediction. */
const RecheckAlert = ({
  recheckedByType,
  totalRechecked,
}: {
  recheckedByType: Record<string, number>;
  totalRechecked: number;
}) => {
  const entries = Object.entries(recheckedByType);

  return (
    <Alert>
      <RefreshCw className="size-5" />
      <AlertTitle>
        {pluralize(totalRechecked, "file")} will be re-checked
      </AlertTitle>
      <AlertDescription className="col-start-2 block min-w-0 [text-wrap:pretty]">
        <p>
          Sync re-reads these files and updates the ones whose content changed.
        </p>
        {entries.length > 1 ? (
          <ul className="mt-2 space-y-0.5">
            {entries.map(([type, count]) => (
              <li key={type} className="flex justify-between gap-4">
                <span>{formatConnectorLabel(type)}</span>
                <span className="tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </AlertDescription>
    </Alert>
  );
};

export const SyncConfirmDialog = ({
  open,
  onOpenChange,
  onConfirm,
  isLoading = false,
  isSyncing = false,
  orphans,
  orphansByType,
  orphansAvailableByType,
  updates,
  updatesByType,
  updatesAvailableByType,
  syncedCount,
  syncedCountByType,
  connectorType,
  isSyncAll = false,
}: SyncConfirmDialogProps) => {
  const handleConfirm = async () => {
    await onConfirm();
    onOpenChange(false);
  };

  const data = summarizeSyncPreview({
    orphans,
    orphansByType,
    orphansAvailableByType,
    updates,
    updatesByType,
    updatesAvailableByType,
    syncedCount,
    syncedCountByType,
    connectorType,
    isSyncAll,
  });

  const {
    orphansByType: normOrphans,
    updatesByType: normUpdates,
    recheckedByType,
    unavailableConnectors,
    totalOrphans,
    totalUpdates,
    totalRechecked,
  } = data;

  const hasDeletes = totalOrphans > 0;
  const hasUnavailable = unavailableConnectors.length > 0;
  const hasUpdates = totalUpdates > 0;
  const hasRechecks = totalRechecked > 0;
  const busy = isLoading || isSyncing;

  const title = isSyncAll ? "Sync all connectors" : "Confirm sync";

  let description: React.ReactNode;
  if (isLoading) {
    description = "Checking what will change…";
  } else if (hasDeletes) {
    description = `Sync will remove ${pluralize(totalOrphans, "file")}.`;
  } else if (hasUnavailable) {
    description = "Some connectors couldn't be checked for deletions.";
  } else if (hasUpdates) {
    description = `Sync will update ${pluralize(totalUpdates, "file")}.`;
  } else if (hasRechecks) {
    description = `Sync will re-check ${pluralize(totalRechecked, "file")}.`;
  } else {
    description = "Everything is already up to date.";
  }

  // CTA variant + copy follows the most-severe state present.
  let ctaVariant: "destructive" | "warning" | "default" = "default";
  let ctaCopy = "Confirm sync";
  if (hasDeletes) {
    ctaVariant = "destructive";
    ctaCopy = "Delete & sync";
  } else if (hasUnavailable) {
    ctaVariant = "warning";
    ctaCopy = "Sync anyway";
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>
            {title}
            {!isSyncAll && connectorType ? (
              <span className="text-muted-foreground font-normal">
                {" "}
                · {formatConnectorLabel(connectorType)}
              </span>
            ) : null}
          </DialogTitle>
          <DialogDescription className="pt-2 text-muted-foreground">
            {description}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="space-y-3">
            {/* Deletes — destructive, most prominent */}
            {hasDeletes ? (
              <DeletesAlert
                orphansByType={normOrphans}
                totalOrphans={totalOrphans}
                isSyncAll={isSyncAll}
              />
            ) : null}

            {/* Unavailable — destructive, surfaces unknown-deletion risk */}
            {hasUnavailable ? (
              <UnavailableAlert connectors={unavailableConnectors} />
            ) : null}

            {/* TODO: Renames section — requires backend support to detect
                renames as a distinct category. Insert between Unavailable
                and Updates when the preview endpoint returns rename data. */}

            {/* Updates — informational: the files that actually changed */}
            {hasUpdates ? (
              <UpdatesAlert
                updatesByType={normUpdates}
                totalUpdates={totalUpdates}
                isSyncAll={isSyncAll}
              />
            ) : null}

            {/* Re-checks — connectors that can't predict what will change */}
            {hasRechecks ? (
              <RecheckAlert
                recheckedByType={recheckedByType}
                totalRechecked={totalRechecked}
              />
            ) : null}

            {!hasDeletes && !hasUnavailable && !hasUpdates && !hasRechecks ? (
              <Alert>
                <Check className="size-5" />
                <AlertTitle>Nothing to change</AlertTitle>
                <AlertDescription className="col-start-2 block min-w-0">
                  <p>No files were added, changed, or removed at the source.</p>
                </AlertDescription>
              </Alert>
            ) : null}
          </div>
        )}

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
            variant={ctaVariant}
            size="sm"
            onClick={handleConfirm}
            disabled={busy}
            loading={isSyncing}
          >
            {ctaVariant === "destructive" ? (
              <Trash2 className="h-3.5 w-3.5" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            {ctaCopy}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
