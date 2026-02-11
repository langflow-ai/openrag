"use client";

import { EllipsisVertical, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { useDeleteDocument } from "@/app/api/mutations/useDeleteDocument";
import { useSyncConnector } from "@/app/api/mutations/useSyncConnector";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DeleteConfirmationDialog } from "./delete-confirmation-dialog";
import { Button } from "./ui/button";

interface KnowledgeActionsDropdownProps {
  filename: string;
  connectorType?: string;
}

// Cloud connector types that support sync
const CLOUD_CONNECTOR_TYPES = new Set(["google_drive", "onedrive", "sharepoint"]);

export const KnowledgeActionsDropdown = ({
  filename,
  connectorType,
}: KnowledgeActionsDropdownProps) => {
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const deleteDocumentMutation = useDeleteDocument();
  const syncConnectorMutation = useSyncConnector();
  const router = useRouter();

  // Check if this file is from a cloud connector (can be synced)
  const isCloudFile = connectorType && CLOUD_CONNECTOR_TYPES.has(connectorType);

  const handleDelete = async () => {
    try {
      await deleteDocumentMutation.mutateAsync({ filename });
      toast.success(`Successfully deleted "${filename}"`);
      setShowDeleteDialog(false);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to delete document",
      );
    }
  };

  const handleSync = async () => {
    if (!connectorType) return;
    
    try {
      toast.info(`Syncing ${connectorType}...`);
      const result = await syncConnectorMutation.mutateAsync(connectorType);
      if (result.status === "no_files") {
        toast.info(result.message || `No ${connectorType} files to sync.`);
      } else if (result.task_ids && result.task_ids.length > 0) {
        toast.success(
          `Sync started for ${connectorType}. Check task notifications for progress.`
        );
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : `Failed to sync ${connectorType}`,
      );
    }
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
          <DropdownMenuItem
            className="text-primary focus:text-primary"
            onClick={() => {
              router.push(
                `/knowledge/chunks?filename=${encodeURIComponent(filename)}`,
              );
            }}
          >
            View chunks
          </DropdownMenuItem>
          {isCloudFile && (
            <DropdownMenuItem
              className="text-primary focus:text-primary"
              disabled={syncConnectorMutation.isPending}
              onClick={handleSync}
            >
              {syncConnectorMutation.isPending ? (
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
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            onClick={() => setShowDeleteDialog(true)}
          >
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DeleteConfirmationDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        title="Delete Document"
        description={`Are you sure you want to delete "${filename}"? This will remove all chunks and data associated with this document. This action cannot be undone.`}
        confirmText="Delete"
        onConfirm={handleDelete}
        isLoading={deleteDocumentMutation.isPending}
      />
    </>
  );
};
