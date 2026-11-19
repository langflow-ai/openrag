"use client";

import { RefreshCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  useDeleteSnapshotImport,
  useShareSnapshotImport,
} from "@/app/api/mutations/useSnapshotImportMutations";
import { useSnapshotImportsQuery } from "@/app/api/queries/useSnapshotImportsQuery";
import { useSnapshotStatusQuery } from "@/app/api/queries/useSnapshotStatusQuery";
import { DeleteConfirmationDialog } from "@/components/delete-confirmation-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/hooks/use-permissions";
import {
  isImportBusy,
  type SnapshotImport,
  type SnapshotImportStatus,
} from "@/lib/opensearch-snapshot";
import { ReimportDialog } from "./reimport-dialog";

const STATUS_LABELS: Record<SnapshotImportStatus, string> = {
  staging: "Staging",
  restoring: "Restoring",
  review: "Needs review",
  active: "Active",
  failed: "Failed",
  deleting: "Deleting",
};

function statusVariant(status: SnapshotImportStatus) {
  if (status === "failed") return "destructive" as const;
  if (status === "active") return "default" as const;
  return "secondary" as const;
}

function jobLabel(imp: SnapshotImport): string | null {
  const { state, kind } = imp.job;
  if (state === "idle") return null;
  // A failed first import is already shown by the status badge.
  if (imp.status === "failed" && kind === "import") return null;
  const noun =
    kind === "reimport" ? "Re-import" : kind === "delete" ? "Delete" : "Import";
  if (state === "queued") return `${noun} queued`;
  if (state === "running") return `${noun} running`;
  if (state === "recovery") return `${noun} recovering`;
  return `${noun} ${state}`;
}

interface ImportsListProps {
  /** Open the wizard on an existing import. */
  onOpenImport: (importId: string) => void;
  pollIntervalMs?: number;
}

export function ImportsList({
  onOpenImport,
  pollIntervalMs,
}: ImportsListProps) {
  const { can, canAny } = usePermissions();
  const canCreate = can("connectors:create");
  const canDelete = canAny(["connectors:delete:own", "connectors:delete:any"]);
  const { data: status } = useSnapshotStatusQuery();
  const { data: imports = [] } = useSnapshotImportsQuery(true, pollIntervalMs);
  const share = useShareSnapshotImport();
  const deleteImport = useDeleteSnapshotImport();
  const [reimportTarget, setReimportTarget] = useState<SnapshotImport | null>(
    null,
  );
  const [deleteTarget, setDeleteTarget] = useState<SnapshotImport | null>(null);
  const privateSupported = status?.private_supported ?? true;

  if (imports.length === 0) return null;

  const toggleShare = async (imp: SnapshotImport, shared: boolean) => {
    try {
      await share.mutateAsync({ importId: imp.id, shared });
    } catch (err) {
      toast.error("Could not change sharing", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteImport.mutateAsync(deleteTarget.id);
    } catch (err) {
      toast.error("Could not delete the import", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold">Imported datasets</h4>
      <ul aria-label="Snapshot imports" className="space-y-2">
        {imports.map((imp) => {
          const busy = isImportBusy(imp);
          const job = jobLabel(imp);
          const shareDisabled =
            !imp.is_owner ||
            busy ||
            imp.status === "failed" ||
            (!privateSupported && imp.shared);
          const shareId = `share-${imp.id}`;
          return (
            <li
              key={imp.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{imp.name}</span>
                  <Badge variant={statusVariant(imp.status)}>
                    {STATUS_LABELS[imp.status] ?? imp.status}
                  </Badge>
                  {job && <Badge variant="outline">{job}</Badge>}
                  {!imp.is_owner && (
                    <Badge variant="outline">Shared with you</Badge>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {imp.snapshot_name} · {imp.source_indices.length}{" "}
                  {imp.source_indices.length === 1 ? "index" : "indices"}
                </p>
                {imp.job.error && imp.job.state === "failed" && (
                  <p className="text-xs text-destructive">{imp.job.error}</p>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Switch
                  id={shareId}
                  checked={imp.shared}
                  disabled={shareDisabled}
                  title={
                    !privateSupported && imp.shared
                      ? "This deployment cannot restrict datasets to a single user"
                      : undefined
                  }
                  onCheckedChange={(checked) => toggleShare(imp, checked)}
                />
                <Label htmlFor={shareId} className="text-sm">
                  {`Share ${imp.name}`}
                </Label>
              </div>

              <div className="flex gap-2">
                {imp.is_owner &&
                  (imp.status === "review" || imp.status === "active") && (
                    <Button
                      variant="outline"
                      size="sm"
                      aria-label={`${imp.status === "review" ? "Review" : "Edit datasets of"} ${imp.name}`}
                      onClick={() => onOpenImport(imp.id)}
                    >
                      {imp.status === "review" ? "Review" : "Edit datasets"}
                    </Button>
                  )}
                {imp.is_owner && imp.status === "active" && (
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={`Re-import ${imp.name}`}
                    disabled={busy || !canCreate}
                    title={
                      canCreate
                        ? undefined
                        : "You do not have permission to create connectors"
                    }
                    onClick={() => setReimportTarget(imp)}
                  >
                    <RefreshCcw className="h-4 w-4" />
                    Re-import
                  </Button>
                )}
                {imp.is_owner && (
                  <Button
                    variant="outline"
                    size="iconMd"
                    className="text-destructive hover:text-destructive"
                    aria-label={`Delete ${imp.name}`}
                    disabled={
                      !canDelete ||
                      (imp.status === "deleting" && busy) ||
                      deleteImport.isPending
                    }
                    title={
                      canDelete
                        ? undefined
                        : "You do not have permission to delete connectors"
                    }
                    onClick={() => setDeleteTarget(imp)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <ReimportDialog
        imp={reimportTarget}
        onClose={() => setReimportTarget(null)}
      />
      <DeleteConfirmationDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={`Delete ${deleteTarget?.name ?? "import"}?`}
        description="This removes the restored datasets from OpenRAG."
        confirmText="Delete"
        onConfirm={confirmDelete}
        isLoading={deleteImport.isPending}
      >
        <p>
          The datasets will no longer be searchable from chat, search or MCP.
          The snapshot in your S3 bucket is not touched.
        </p>
      </DeleteConfirmationDialog>
    </div>
  );
}
