"use client";

import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EllipsisVertical } from "lucide-react";
import { Button } from "./ui/button";
import { DeleteConfirmationDialog } from "./confirmation-dialog";
import { useDeleteDocument } from "@/app/api/mutations/useDeleteDocument";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

interface KnowledgeActionsDropdownProps {
  filename: string;
}

export const KnowledgeActionsDropdown = ({
  filename,
}: KnowledgeActionsDropdownProps) => {
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const deleteDocumentMutation = useDeleteDocument();
  const router = useRouter();

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
          {/* //TODO: Implement rename and sync */}
          {/* <DropdownMenuItem
            className="text-primary focus:text-primary"
            onClick={() => alert("Not implemented")}
          >
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            className="text-primary focus:text-primary"
            onClick={() => alert("Not implemented")}
          >
            Sync
          </DropdownMenuItem> */}
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
