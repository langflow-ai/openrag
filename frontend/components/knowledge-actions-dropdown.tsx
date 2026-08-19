"use client";

import {
  AlertCircle,
  Download,
  EllipsisVertical,
  Eye,
  RefreshCw,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useDeleteDocument } from "@/app/api/mutations/useDeleteDocument";
import {
  type SyncPreviewResponse,
  useSyncConnector,
  useSyncConnectorPreview,
} from "@/app/api/mutations/useSyncConnector";
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
import { getDownloadSourceUrl, getSourcePreviewKind } from "@/lib/source-url";
import { DeleteConfirmationDialog } from "./delete-confirmation-dialog";
import { RequirePermission } from "./require-permission";
import { SourcePreviewDialog } from "./source-preview-dialog";
import { SyncConfirmDialog } from "./sync-confirm-dialog";
import { Button } from "./ui/button";

interface KnowledgeActionsDropdownProps {
  filename: string;
  sourceUrl?: string;
  connectorType?: string;
}

// Cloud connector types that support sync
const CLOUD_CONNECTOR_TYPES = new Set([
  "google_drive",
  "onedrive",
  "sharepoint",
]);

export const KnowledgeActionsDropdown = ({
  filename,
  sourceUrl,
  connectorType,
}: KnowledgeActionsDropdownProps) => {
  const { refreshTasks } = useTask();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const deleteDocumentMutation = useDeleteDocument();
  const syncConnectorMutation = useSyncConnector();
  const syncPreviewMutation = useSyncConnectorPreview();
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [syncPreview, setSyncPreview] = useState<SyncPreviewResponse | null>(
    null,
  );
  const { data: connectors = [] } = useGetConnectorsQuery();
  const router = useRouter();
  const downloadSourceUrl = getDownloadSourceUrl(sourceUrl);
  const previewKind = getSourcePreviewKind(filename);

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

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="hover:bg-transparent"
            aria-label={`Actions for ${filename}`}
          >
            <EllipsisVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start" sideOffset={-10}>
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
          {downloadSourceUrl && previewKind && (
            <DropdownMenuItem
              className="text-primary focus:text-primary cursor-pointer"
              onClick={() => setPreviewOpen(true)}
            >
              <Eye className="h-4 w-4 mr-2" />
              Preview source
            </DropdownMenuItem>
          )}
          {downloadSourceUrl && (
            <DropdownMenuItem asChild>
              <a
                href={downloadSourceUrl}
                download={filename}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary focus:text-primary cursor-pointer"
                onClick={() =>
                  trackButton({
                    CTA: "Download Source",
                    elementId: "download-source-button",
                    namespace: "knowledge",
                  })
                }
              >
                <Download className="h-4 w-4 mr-2" />
                Download source
              </a>
            </DropdownMenuItem>
          )}
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
                      is not connected. Connect it in Settings to enable sync.
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
        </DropdownMenuContent>
      </DropdownMenu>

      {downloadSourceUrl && previewKind && (
        <SourcePreviewDialog
          filename={filename}
          kind={previewKind}
          open={previewOpen}
          onOpenChange={setPreviewOpen}
          sourceUrl={downloadSourceUrl}
        />
      )}

      <DeleteConfirmationDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title="Delete document"
        description="Are you sure you want to delete this document?"
        confirmText="Delete"
        onConfirm={handleDelete}
        isLoading={deleteDocumentMutation.isPending}
      >
        <p className="my-2">
          This will remove all chunks and data associated with this document.
          This action cannot be undone.
        </p>
        <p className="my-2">Document to be deleted:</p>
        {formatFilesToDelete([{ filename }])}
      </DeleteConfirmationDialog>

      <SyncConfirmDialog
        open={syncDialogOpen}
        onOpenChange={setSyncDialogOpen}
        onConfirm={handleConfirmSync}
        isLoading={syncPreviewMutation.isPending || syncPreview === null}
        isSyncing={syncConnectorMutation.isPending}
        connectorType={connectorType}
        orphans={syncPreview?.orphans}
        syncedCount={syncPreview?.synced_count}
      />
    </>
  );
};
