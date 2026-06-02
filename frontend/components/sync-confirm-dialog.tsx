"use client";

import { AlertTriangle, Check, Loader2, RefreshCw, Trash2 } from "lucide-react";
import type React from "react";
import type { OrphanFile } from "@/app/api/mutations/useSyncConnector";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
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
  /** Single-connector mode: total files that will be updated. */
  syncedCount?: number;
  /** Sync-all mode: per-connector update counts. */
  syncedCountByType?: Record<string, number>;
  /** Single-connector mode: connector type for the title (e.g. "sharepoint"). */
  connectorType?: string;
  /** When true, render the sync-all view (groups by connector_type). */
  isSyncAll?: boolean;
}

interface NormalizedData {
  /** Deletions grouped by connector_type (single-mode collapses to one entry). */
  orphansByType: Record<string, OrphanFile[]>;
  /** Update counts grouped by connector_type. */
  updatesByType: Record<string, number>;
  /** Connectors whose orphan detection couldn't complete. */
  unavailableConnectors: string[];
  totalOrphans: number;
  totalUpdates: number;
}

const normalize = (
  props: Pick<
    SyncConfirmDialogProps,
    | "orphans"
    | "orphansByType"
    | "orphansAvailableByType"
    | "syncedCount"
    | "syncedCountByType"
    | "connectorType"
    | "isSyncAll"
  >,
): NormalizedData => {
  const {
    orphans,
    orphansByType,
    orphansAvailableByType,
    syncedCount,
    syncedCountByType,
    connectorType,
    isSyncAll,
  } = props;

  const normalizedOrphans: Record<string, OrphanFile[]> = isSyncAll
    ? Object.fromEntries(
        Object.entries(orphansByType ?? {}).filter(
          ([, list]) => list.length > 0,
        ),
      )
    : orphans && orphans.length > 0 && connectorType
      ? { [connectorType]: orphans }
      : {};

  const normalizedUpdates: Record<string, number> = isSyncAll
    ? Object.fromEntries(
        Object.entries(syncedCountByType ?? {}).filter(([, n]) => n > 0),
      )
    : syncedCount && syncedCount > 0 && connectorType
      ? { [connectorType]: syncedCount }
      : {};

  const unavailableConnectors = Object.entries(orphansAvailableByType ?? {})
    .filter(([, available]) => !available)
    .map(([type]) => type);

  const totalOrphans = Object.values(normalizedOrphans).reduce(
    (sum, list) => sum + list.length,
    0,
  );
  const totalUpdates = Object.values(normalizedUpdates).reduce(
    (sum, n) => sum + n,
    0,
  );

  return {
    orphansByType: normalizedOrphans,
    updatesByType: normalizedUpdates,
    unavailableConnectors,
    totalOrphans,
    totalUpdates,
  };
};

const DeletesAlert: React.FC<{
  orphansByType: Record<string, OrphanFile[]>;
  totalOrphans: number;
  isSyncAll: boolean;
}> = ({ orphansByType, totalOrphans, isSyncAll }) => {
  const renderList = (list: OrphanFile[]) => (
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
                    {renderList(list)}
                    {index < entries.length - 1 ? (
                      <Separator className="mt-3" />
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="pr-2">{renderList(entries[0]?.[1] ?? [])}</div>
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

const UnavailableAlert: React.FC<{ connectors: string[] }> = ({
  connectors,
}) => (
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

const UpdatesAlert: React.FC<{
  updatesByType: Record<string, number>;
  totalUpdates: number;
  isSyncAll: boolean;
}> = ({ updatesByType, totalUpdates, isSyncAll }) => {
  const entries = Object.entries(updatesByType);

  return (
    <Alert>
      <RefreshCw className="size-5" />
      <AlertTitle>{pluralize(totalUpdates, "file")} will be updated</AlertTitle>
      {isSyncAll && entries.length > 1 ? (
        <AlertDescription className="col-start-2 block min-w-0">
          <ul className="mt-1 space-y-0.5">
            {entries.map(([type, count]) => (
              <li key={type} className="flex justify-between gap-4">
                <span>{formatConnectorLabel(type)}</span>
                <span className="tabular-nums">{count}</span>
              </li>
            ))}
          </ul>
        </AlertDescription>
      ) : null}
    </Alert>
  );
};

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

  const data = normalize({
    orphans,
    orphansByType,
    orphansAvailableByType,
    syncedCount,
    syncedCountByType,
    connectorType,
    isSyncAll,
  });

  const {
    orphansByType: normOrphans,
    updatesByType,
    unavailableConnectors,
    totalOrphans,
    totalUpdates,
  } = data;

  const hasDeletes = totalOrphans > 0;
  const hasUnavailable = unavailableConnectors.length > 0;
  const hasUpdates = totalUpdates > 0;
  const busy = isLoading || isSyncing;

  const title = isSyncAll ? "Sync all connectors" : "Confirm sync";

  let description: React.ReactNode;
  if (isLoading) {
    description = "Checking what will change…";
  } else if (hasDeletes) {
    description = `Sync will remove ${pluralize(totalOrphans, "file")}.`;
  } else if (hasUnavailable) {
    description = "Some connectors couldn't be checked for deletions.";
  } else {
    description = `Sync will update ${pluralize(totalUpdates, "file")}.`;
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

            {/* Updates — informational, count only */}
            {hasUpdates ? (
              <UpdatesAlert
                updatesByType={updatesByType}
                totalUpdates={totalUpdates}
                isSyncAll={isSyncAll}
              />
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
