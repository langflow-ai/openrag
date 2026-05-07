"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import {
  type RenameDocumentResponse,
  useRenameDocument,
} from "@/app/api/mutations/useRenameDocument";
import type { KnowledgeFilter } from "@/app/api/queries/useGetFiltersSearchQuery";
import type { RenameDialogTarget } from "@/components/knowledge-actions-dropdown";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { useTask } from "@/contexts/task-context";

export function useKnowledgeRenameDocument() {
  const queryClient = useQueryClient();
  const { refreshTasks } = useTask();
  const { selectedFilter, setSelectedFilter } = useKnowledgeFilter();
  const renameDocumentMutation = useRenameDocument();

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameCurrentFilename, setRenameCurrentFilename] = useState("");
  const [renameDisplayLabel, setRenameDisplayLabel] = useState("");
  const [renameNewFilename, setRenameNewFilename] = useState("");
  const [renameDocumentId, setRenameDocumentId] = useState<
    string | undefined
  >();
  const [renamePartialSummary, setRenamePartialSummary] = useState<{
    updated_chunks: number;
    remaining_old_chunks: number;
    matched_chunks: number;
  } | null>(null);
  const [renameInProgress, setRenameInProgress] = useState(false);

  const openRenameDialog = useCallback((target: RenameDialogTarget) => {
    const label = target.filename.trim();
    setRenameDisplayLabel(label);
    setRenameCurrentFilename(
      (target.renameCurrentFilename ?? target.filename).trim(),
    );
    setRenameDocumentId(target.documentId);
    setRenameNewFilename(target.filename);
    setRenamePartialSummary(null);
    setRenameDialogOpen(true);
  }, []);

  const handleRenameDialogOpenChange = useCallback((open: boolean) => {
    setRenameDialogOpen(open);
    if (!open) {
      setRenameNewFilename("");
      setRenamePartialSummary(null);
    }
  }, []);

  const handleRenameSave = useCallback(async () => {
    const next = renameNewFilename.trim();
    if (!next) {
      toast.error("Enter a new file name");
      return;
    }
    const trimIdx = renameCurrentFilename.trim();
    const trimDisp = renameDisplayLabel.trim();
    if (next === trimIdx) {
      toast.error("New name must differ from the current name");
      return;
    }
    if (trimDisp && trimDisp !== trimIdx && next === trimDisp) {
      toast.error("Enter a different name", {
        description:
          "The list label can differ from the stored file name. Type a new name before saving.",
        id: "knowledge-rename-validation",
        duration: 7000,
      });
      return;
    }
    setRenameInProgress(true);
    try {
      const hadPartialBefore = renamePartialSummary !== null;

      const result = await renameDocumentMutation.mutateAsync({
        current_filename: renameCurrentFilename,
        new_filename: next,
        document_id: renameDocumentId ?? null,
      });

      await queryClient.invalidateQueries({ queryKey: ["search"] });
      if (!result.partial) {
        await queryClient.refetchQueries({
          queryKey: ["knowledge-filters", "all"],
        });
        const freshFilters = queryClient.getQueryData<KnowledgeFilter[]>([
          "knowledge-filters",
          "all",
        ]);
        if (selectedFilter && freshFilters?.length) {
          const nextFilter = freshFilters.find(
            (f) => f.id === selectedFilter.id,
          );
          if (nextFilter) setSelectedFilter(nextFilter);
        }
      }
      await refreshTasks();

      const persistRenameDocumentId = (r: RenameDocumentResponse) => {
        const raw = r.document_id;
        if (raw == null) return;
        const id = String(raw).trim();
        if (id) setRenameDocumentId(id);
      };

      if (result.partial) {
        persistRenameDocumentId(result);
        const updated = result.updated_chunks ?? 0;
        const remaining = result.remaining_old_chunks ?? 0;
        const matched = result.matched_chunks ?? 0;
        setRenamePartialSummary({
          updated_chunks: updated,
          remaining_old_chunks: remaining,
          matched_chunks: matched,
        });
        toast.warning("Rename partially applied", {
          description: `${updated} chunk(s) updated; ${remaining} still use the old name. Continue to rename the remaining chunks.`,
        });
        return;
      }

      setRenamePartialSummary(null);
      setRenameDialogOpen(false);
      setRenameNewFilename("");

      persistRenameDocumentId(result);

      if (result.success && result.idempotent) {
        toast.success(
          hadPartialBefore ? "Rename complete" : "Name already in sync",
          {
            description: `Every indexed chunk uses "${next}".`,
          },
        );
        return;
      }

      if (
        result.success &&
        result.resumed &&
        (result.updated_chunks || 0) > 0
      ) {
        toast.success("Rename complete", {
          description: `All remaining chunks now use "${next}".`,
        });
        return;
      }

      if (
        result.success &&
        (result.updated_chunks || 0) > 0 &&
        hadPartialBefore
      ) {
        toast.success("Rename complete", {
          description: `All chunks now use "${next}".`,
        });
        return;
      }

      if (result.success && (result.updated_chunks || 0) > 0) {
        toast.success("Document renamed", {
          description: `${renameCurrentFilename} → ${next}`,
        });
      } else {
        toast.warning("Rename finished but no chunks were updated.");
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to rename document",
        {
          id: "knowledge-rename-error",
          duration: 8000,
        },
      );
    } finally {
      setRenameInProgress(false);
    }
  }, [
    queryClient,
    renameCurrentFilename,
    renameDisplayLabel,
    renameDocumentId,
    renameDocumentMutation,
    renameNewFilename,
    renamePartialSummary,
    refreshTasks,
    selectedFilter,
    setSelectedFilter,
  ]);

  return {
    openRenameDialog,
    renameInProgress,
    renameDialogProps: {
      open: renameDialogOpen,
      onOpenChange: handleRenameDialogOpenChange,
      newFilename: renameNewFilename,
      onNewFilenameChange: setRenameNewFilename,
      partialSummary: renamePartialSummary,
      flowInProgress: renameInProgress,
      isMutationPending: renameDocumentMutation.isPending,
      onSave: handleRenameSave,
    },
  };
}
