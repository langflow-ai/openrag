"use client";

import { Loader2 } from "lucide-react";
import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface KnowledgeRenamePartialSummary {
  updated_chunks: number;
  remaining_old_chunks: number;
  matched_chunks: number;
}

export interface KnowledgeRenameDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  newFilename: string;
  onNewFilenameChange: (value: string) => void;
  partialSummary: KnowledgeRenamePartialSummary | null;
  /** Covers API request plus query invalidation / refetch after save. */
  flowInProgress: boolean;
  isMutationPending: boolean;
  onSave: () => void | Promise<void>;
}

export function KnowledgeRenameDocumentDialog({
  open,
  onOpenChange,
  newFilename,
  onNewFilenameChange,
  partialSummary,
  flowInProgress,
  isMutationPending,
  onSave,
}: KnowledgeRenameDocumentDialogProps) {
  const primaryActionLabel = useMemo(() => {
    if (!flowInProgress) {
      return partialSummary ? "Continue" : "Save";
    }
    if (isMutationPending) {
      return partialSummary ? "Renaming chunks…" : "Saving…";
    }
    return "Syncing list…";
  }, [flowInProgress, isMutationPending, partialSummary]);

  const handleOpenChange = (next: boolean) => {
    if (!next && flowInProgress) {
      return;
    }
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="flex h-[min(28rem,85vh)] max-h-[85vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md"
        onPointerDownOutside={(e) =>
          flowInProgress ? e.preventDefault() : undefined
        }
        onEscapeKeyDown={(e) =>
          flowInProgress ? e.preventDefault() : undefined
        }
      >
        <div className="shrink-0 px-6 pt-6 pr-12">
          <DialogHeader className="space-y-1.5 p-0 text-left">
            <DialogTitle>Rename document</DialogTitle>
            <DialogDescription>
              Updates the display name for this file in search and knowledge.
              Document content and internal id are unchanged.
            </DialogDescription>
          </DialogHeader>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6">
          <div className="grid gap-2 py-2">
            <Label htmlFor="knowledge-rename-filename-input">New name</Label>
            <Input
              id="knowledge-rename-filename-input"
              value={newFilename}
              onChange={(e) => onNewFilenameChange(e.target.value)}
              disabled={flowInProgress}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void onSave();
                }
              }}
              autoFocus
            />
            <div aria-live="polite">
              {partialSummary ? (
                <div className="rounded-md border border-amber-500/25 bg-amber-500/5 px-3 py-2.5">
                  <p className="text-pretty text-sm text-amber-800 line-clamp-4 dark:text-amber-200">
                    Partial rename: {partialSummary.updated_chunks} of{" "}
                    {partialSummary.matched_chunks} matching chunk(s) now use
                    &quot;{newFilename.trim()}&quot;.{" "}
                    {partialSummary.remaining_old_chunks} still use the old
                    name. Continue to rename the remaining chunks or Cancel to
                    stop.
                  </p>
                </div>
              ) : null}
            </div>
          </div>
        </div>
        <div className="shrink-0 border-t bg-background px-6 py-4">
          <DialogFooter className="flex flex-row items-center justify-end gap-2 p-0 sm:space-x-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={flowInProgress}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void onSave()}
              disabled={flowInProgress}
              className="min-w-[7.5rem]"
            >
              {flowInProgress ? (
                <Loader2
                  className="mr-2 h-4 w-4 shrink-0 animate-spin"
                  aria-hidden
                />
              ) : null}
              {primaryActionLabel}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
