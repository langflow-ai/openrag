"use client";

import { AlertCircle, EllipsisVertical, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useDeleteDocument } from "@/app/api/mutations/useDeleteDocument";
import {
  type SyncPreviewResponse,
  useSyncConnector,
  useSyncConnectorPreview,
} from "@/app/api/mutations/useSyncConnector";
import {
  useDeleteWebsiteSourcePageMutation,
  useSyncWebsiteSourceMutation,
} from "@/app/api/mutations/useWebsiteSourceMutation";
import { useGetConnectorsQuery } from "@/app/api/queries/useGetConnectorsQuery";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTask } from "@/contexts/task-context";
import { usePermissions } from "@/hooks/use-permissions";
import { trackButton } from "@/lib/analytics";
import { formatFilesToDelete } from "@/lib/format-files-to-delete";
import { DeleteConfirmationDialog } from "./delete-confirmation-dialog";
import { RequirePermission } from "./require-permission";
import { SyncConfirmDialog } from "./sync-confirm-dialog";
import { Button } from "./ui/button";

interface KnowledgeActionsDropdownProps {
  filename: string;
  connectorType?: string;
  webSourceId?: string;
  webChildCount?: number;
}

// Cloud connector types that support sync
const CLOUD_CONNECTOR_TYPES = new Set([
  "google_drive",
  "onedrive",
  "sharepoint",
]);

export const KnowledgeActionsDropdown = ({
  filename,
  connectorType,
  webSourceId,
  webChildCount,
}: KnowledgeActionsDropdownProps) => {
  const { refreshTasks } = useTask();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const deleteDocumentMutation = useDeleteDocument();
  const syncWebsiteSourceMutation = useSyncWebsiteSourceMutation();
  const deleteWebsiteSourceMutation = useDeleteWebsiteSourcePageMutation();
  const syncConnectorMutation = useSyncConnector();
  const syncPreviewMutation = useSyncConnectorPreview();
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [syncPreview, setSyncPreview] = useState<SyncPreviewResponse | null>(
    null,
  );
  const { data: connectors = [] } = useGetConnectorsQuery();
  const router = useRouter();

  // Check if this file is from a cloud connector (can be synced)
  const isCloudFile = connectorType && CLOUD_CONNECTOR_TYPES.has(connectorType);

  // Check if the connector is connected
  const isConnected = useMemo(() => {
    if (!connectorType) return false;
    const connector = connectors.find((c) => c.type === connectorType);
    return connector?.status === "connected";
  }, [connectors, connectorType]);

  const handleDelete = async () => {
    try {
      const result = await deleteDocumentMutation.mutateAsync({ filename });
      await refreshTasks();
      if ((result.deleted_chunks || 0) > 0) {
        toast.success("Successfully deleted document", {
          description: formatFilesToDelete([{ filename }], 1),
        });
      } else {
        toast.warning(
          "No document chunks were deleted. The file may be missing or not deletable in your current context.",
        );
      }
      setShowDeleteDialog(false);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to delete document",
      );
      setShowDeleteDialog(false);
    }
  };

  const handleOpenSyncDialog = async () => {
    if (!connectorType || !isConnected) return;
    setSyncPreview(null);
    setSyncDialogOpen(true);
    try {
      const preview = await syncPreviewMutation.mutateAsync(connectorType);
      setSyncPreview(preview);
    } catch (error) {
      setSyncDialogOpen(false);
      toast.error(
        error instanceof Error ? error.message : "Failed to preview sync",
      );
    }
  };

  const handleConfirmSync = async () => {
    if (!connectorType) return;
    try {
      const result = await syncConnectorMutation.mutateAsync({ connectorType });
      if (result.status === "no_files") {
        toast.info(result.message || `No ${connectorType} files to sync.`);
      } else if (result.task_ids && result.task_ids.length > 0) {
        toast.success(
          `Sync started for ${connectorType}. Check task notifications for progress.`,
        );
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : `Failed to sync ${connectorType}`,
      );
    }
  };

  const syncWebsite = async () => {
    if (!webSourceId) return;
    try {
      await syncWebsiteSourceMutation.mutateAsync({ sourceId: webSourceId });
      toast.success("Website sync started");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not start website sync",
      );
    }
  };

  const deleteWebsite = async () => {
    if (!webSourceId) return;
    await deleteWebsiteSourceMutation.mutateAsync({ sourceId: webSourceId });
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" className="hover:bg-transparent">
            <EllipsisVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start" sideOffset={-10}>
          {webSourceId ? (
            <>
              <DropdownMenuItem
                className="text-primary focus:text-primary cursor-pointer"
                disabled={syncWebsiteSourceMutation.isPending}
                onClick={syncWebsite}
              >
                <RefreshCw className="mr-2 h-4 w-4" />
                Sync
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive focus:text-destructive cursor-pointer"
                onClick={() => setShowDeleteDialog(true)}
              >
                Delete
              </DropdownMenuItem>
            </>
          ) : (
            <>
              <DropdownMenuItem
                className="text-primary focus:text-primary cursor-pointer"
                onClick={() => {
                  trackButton({
                    CTA: "View Chunks",
                    elementId: "view-chunks-button",
                    namespace: "knowledge",
                  });
                  router.push(
                    `/knowledge/chunks?filename=${encodeURIComponent(filename)}`,
                  );
                }}
              >
                View chunks
              </DropdownMenuItem>
              {isCloudFile && (
                <TooltipProvider>
                  <Tooltip delayDuration={0}>
                    <TooltipTrigger asChild>
                      <div className="w-full">
                        <DropdownMenuItem
                          className="text-primary focus:text-primary cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                          disabled={
                            syncConnectorMutation.isPending ||
                            syncPreviewMutation.isPending ||
                            !isConnected
                          }
                          onClick={(e) => {
                            if (!isConnected) {
                              e.preventDefault();
                              return;
                            }
                            trackButton({
                              CTA: "Sync File",
                              elementId: "sync-file-button",
                              namespace: "knowledge",
                              payload: { connector_type: connectorType },
                            });
                            handleOpenSyncDialog();
                          }}
                        >
                          {syncConnectorMutation.isPending ||
                          syncPreviewMutation.isPending ? (
                            <>
                              <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                              Syncing...
                            </>
                          ) : (
                            <>
                              <RefreshCw className="h-4 w-4 mr-2" />
                              Sync
                            </>
                          )}
                          {!isConnected && (
                            <AlertCircle className="h-3.5 w-3.5 ml-auto text-muted-foreground opacity-70" />
                          )}
                        </DropdownMenuItem>
                      </div>
                    </TooltipTrigger>
                    {!isConnected && (
                      <TooltipContent side="right">
                        <p className="max-w-[200px] text-xs">
                          {connectorType.charAt(0).toUpperCase() +
                            connectorType.slice(1)}{" "}
                          is not connected. Connect it in Settings to enable
                          sync.
                        </p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                </TooltipProvider>
              )}
              <RequirePermission
                anyOf={["knowledge:delete:own", "knowledge:delete:anonymous"]}
              >
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive cursor-pointer"
                  onClick={() => {
                    trackButton({
                      CTA: "Delete Document",
                      elementId: "delete-document-button",
                      namespace: "knowledge",
                    });
                    setShowDeleteDialog(true);
                  }}
                >
                  Delete
                </DropdownMenuItem>
              </RequirePermission>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <DeleteConfirmationDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title={webSourceId ? "Delete website source" : "Delete document"}
        description={
          webSourceId
            ? `Delete this website source and its ${webChildCount || 0} child pages?`
            : "Are you sure you want to delete this document?"
        }
        confirmText="Delete"
        onConfirm={webSourceId ? deleteWebsite : handleDelete}
        isLoading={
          deleteDocumentMutation.isPending ||
          deleteWebsiteSourceMutation.isPending
        }
      >
        {!webSourceId && (
          <p className="my-2">
            This will remove all chunks and data associated with this document.
            This action cannot be undone.
          </p>
        )}
        {webSourceId ? (
          <p className="my-2">
            All of the website&apos;s indexed child pages and chunks will be
            removed.
          </p>
        ) : (
          <>
            <p className="my-2">Document to be deleted:</p>
            {formatFilesToDelete([{ filename }])}
          </>
        )}
      </DeleteConfirmationDialog>

      <SyncConfirmDialog
        open={syncDialogOpen}
        onOpenChange={setSyncDialogOpen}
        onConfirm={handleConfirmSync}
        isLoading={syncPreviewMutation.isPending || syncPreview === null}
        isSyncing={syncConnectorMutation.isPending}
        connectorType={connectorType}
        orphans={syncPreview?.orphans}
        orphansAvailableByType={
          connectorType && syncPreview
            ? { [connectorType]: syncPreview.orphans_available }
            : undefined
        }
        updates={syncPreview?.updates}
        // Every connector in CLOUD_CONNECTOR_TYPES re-reads each file during
        // sync and decides then, so this is false and the dialog reports
        // "re-checked" rather than a count it cannot know in advance.
        updatesAvailableByType={
          connectorType && syncPreview
            ? { [connectorType]: syncPreview.updates_available }
            : undefined
        }
        syncedCount={syncPreview?.synced_count}
      />
    </>
  );
};
