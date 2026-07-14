"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";

export interface DuplicateDialogPending<F, M = undefined> {
  /** Full file list to resubmit with replace=true when the user overwrites. */
  allFiles: F[];
  /** Files with no existing duplicate — synced as-is when the user skips. */
  nonDuplicateFiles: F[];
  duplicateNames: string[];
  duplicateCount: number;
  /** Caller-specific context needed to resubmit (e.g. which connector to sync against). */
  meta?: M;
}

interface UseDuplicateDialogFlowOptions<F, M> {
  /** Performs the actual sync/upload. Called for both "Overwrite duplicates"
   * (replace=true, full file list) and "Skip duplicates & continue"
   * (replace=false, non-duplicate files only). */
  onSubmit: (
    files: F[],
    replaceDuplicates: boolean,
    pending: DuplicateDialogPending<F, M>,
  ) => void | Promise<void>;
  /** Message shown when every file selected was a duplicate and got skipped. */
  allSkippedMessage?: (pending: DuplicateDialogPending<F, M>) => string;
}

/**
 * Drives the shared confirmation-dialog state machine used everywhere a
 * connector sync or upload can hit already-ingested files: check duplicates,
 * then either overwrite, skip-and-continue, or cancel.
 *
 * Dismissing the dialog via the X button, outside click, or Escape must be a
 * true no-op — only the explicit "Skip duplicates & continue" button should
 * trigger a sync of the non-duplicate files. `handleSkip` (wired to the
 * dialog's onSkip prop) and `handleOpenChange` (wired to onOpenChange) keep
 * those two paths separate.
 */
export function useDuplicateDialogFlow<F, M = undefined>({
  onSubmit,
  allSkippedMessage = (pending) =>
    `All ${pending.duplicateCount} file(s) already exist. Nothing was synced.`,
}: UseDuplicateDialogFlowOptions<F, M>) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<DuplicateDialogPending<F, M> | null>(
    null,
  );

  // Call once a duplicate check finds duplicates, to show the confirmation dialog.
  const openDialog = useCallback((next: DuplicateDialogPending<F, M>) => {
    setPending(next);
    setDialogOpen(true);
  }, []);

  const handleOverwrite = useCallback(() => {
    if (!pending) return;
    onSubmit(pending.allFiles, true, pending);
  }, [pending, onSubmit]);

  const handleSkip = useCallback(() => {
    if (!pending) return;
    if (pending.nonDuplicateFiles.length > 0) {
      onSubmit(pending.nonDuplicateFiles, false, pending);
    } else {
      toast.info(allSkippedMessage(pending));
    }
  }, [pending, onSubmit, allSkippedMessage]);

  const handleOpenChange = useCallback((open: boolean) => {
    if (!open) {
      setPending(null);
    }
    setDialogOpen(open);
  }, []);

  return {
    dialogOpen,
    duplicateNames: pending?.duplicateNames,
    duplicateCount: pending?.duplicateCount,
    openDialog,
    handleOverwrite,
    handleSkip,
    handleOpenChange,
  };
}
