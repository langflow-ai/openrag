"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useDeleteDocument } from "@/app/api/mutations/useDeleteDocument";
import { useDismissTaskFilesMutation } from "@/app/api/mutations/useDismissTaskFilesMutation";
import type { File } from "@/app/api/queries/useGetSearchQuery";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTask } from "@/contexts/task-context";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { RequirePermission } from "./require-permission";
import { Button } from "./ui/button";

interface KnowledgeRowActionsProps {
  file: File;
  /** Task that owns this failed row, resolved by the caller. */
  taskId: string | null;
}

/**
 * Delete action for failed knowledge rows: clears any indexed chunks and dismisses
 * the failed task entry so the row leaves the list. Active rows use
 * KnowledgeActionsDropdown; other statuses have no row action.
 */
export const KnowledgeRowActions = ({
  file,
  taskId,
}: KnowledgeRowActionsProps) => {
  const { refreshTasks } = useTask();
  const dismissMutation = useDismissTaskFilesMutation();
  const deleteDocumentMutation = useDeleteDocument();
  const [isRemoving, setIsRemoving] = useState(false);

  if ((file.status ?? "active") !== "failed") {
    return null;
  }

  const sourceUrl = file.source_url?.trim();

  const handleDelete = async () => {
    trackButton({
      CTA: "Delete Failed Document",
      elementId: "knowledge-delete-failed-button",
      namespace: "knowledge",
    });
    setIsRemoving(true);
    try {
      // A partially-indexed failure may have chunks; a never-indexed one 404s.
      // Best-effort cleanup so the row does not reappear as "active".
      try {
        await deleteDocumentMutation.mutateAsync({ filename: file.filename });
      } catch {
        // Expected when the failed document never produced any chunks.
      }
      if (taskId && sourceUrl) {
        await dismissMutation.mutateAsync({ taskId, filePaths: [sourceUrl] });
      }
      await refreshTasks();
      toast.success("Removed from list");
    } catch (error) {
      toast.error("Failed to remove document", {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setIsRemoving(false);
    }
  };

  return (
    <RequirePermission
      anyOf={["knowledge:delete:own", "knowledge:delete:anonymous"]}
    >
      <TooltipProvider>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              className={cn(
                "h-8 w-8 p-0 hover:bg-muted hover:text-destructive",
              )}
              aria-label="Delete from list"
              data-testid="knowledge-row-delete"
              disabled={isRemoving}
              onClick={handleDelete}
            >
              <Trash2 className="h-4 w-4 text-muted-foreground" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Delete from list</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </RequirePermission>
  );
};
