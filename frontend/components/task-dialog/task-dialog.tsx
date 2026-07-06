"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { cn } from "@/lib/utils";
import { TaskDialogFileList } from "./file-list";
import { TaskDialogHeader } from "./header";
import { useTaskDialog } from "./use-task-dialog";

interface TaskDialogProps {
  open: boolean;
  task_id: string;
  onOpenChange: (open: boolean) => void;
  onClose: () => void;
}

function TaskDialogContent({
  open,
  task_id,
  onClose,
}: Pick<TaskDialogProps, "open" | "task_id" | "onClose">) {
  const isCloudBrand = useIsCloudBrand();
  const {
    task,
    isLoading,
    isError,
    fileEntries,
    fileTypes,
    categoryCounts,
    sortedEntries,
    retryIngestionEntries,
    retryIngestionSelectedCount,
    allRetryIngestionsSelected,
    toggleSelectAllRetryIngestions,
    search,
    setSearch,
    fileType,
    setFileType,
    statusCategory,
    setStatusCategory,
    expandedPath,
    setExpandedPath,
    nameSort,
    toggleNameSort,
    retryableCount,
    selectedCount,
    selectedPaths,
    selectablePaths,
    allSelectableSelected,
    toggleSelectedPath,
    toggleSelectAllVisible,
    isRetrying,
    retryingTarget,
    handleRetryAll,
    handleRetrySelected,
  } = useTaskDialog(open, task_id);

  const filtersDisabled = !task;
  // Always offer "All file types"; only disable while task data is loading.
  const fileTypeDisabled = !task;
  const showRetryActions = retryableCount > 0;
  const isCancelOnly = !showRetryActions;

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col overflow-hidden",
        isCloudBrand
          ? "bg-layer-contextual font-ibm-plex-sans"
          : "bg-task-dialog-oss",
      )}
    >
      <TaskDialogHeader
        taskId={task_id}
        taskStatus={task?.status}
        search={search}
        onSearchChange={setSearch}
        fileType={fileType}
        onFileTypeChange={setFileType}
        fileTypes={fileTypes}
        statusCategory={statusCategory}
        onStatusCategoryChange={setStatusCategory}
        categoryCounts={categoryCounts}
        filtersDisabled={filtersDisabled}
        fileTypeDisabled={fileTypeDisabled}
      />

      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col overflow-hidden",
          isCloudBrand ? "bg-layer-contextual" : "bg-task-dialog-oss px-4",
        )}
      >
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading task…</p>
        ) : isError || !task ? (
          <p className="text-sm text-muted-foreground">Task not found.</p>
        ) : fileEntries.length === 0 && retryableCount === 0 ? (
          <p className="text-sm text-muted-foreground">
            No files in this task.
          </p>
        ) : (
          <TaskDialogFileList
            task={task}
            entries={sortedEntries}
            retryIngestionEntries={retryIngestionEntries}
            totalSourceCount={sortedEntries.length}
            totalSourceCountAll={fileEntries.length}
            nameSort={nameSort}
            onToggleNameSort={toggleNameSort}
            expandedPath={expandedPath}
            onExpandedPathChange={setExpandedPath}
            retryIngestionCount={retryableCount}
            selectablePaths={selectablePaths}
            selectedPaths={selectedPaths}
            allSelectableSelected={allSelectableSelected}
            onToggleSelectedPath={toggleSelectedPath}
            onToggleSelectAllVisible={toggleSelectAllVisible}
            allRetryIngestionsSelected={allRetryIngestionsSelected}
            onToggleSelectAllRetryIngestions={toggleSelectAllRetryIngestions}
            selectedCount={selectedCount}
            retryIngestionSelectedCount={retryIngestionSelectedCount}
            retryingTarget={retryingTarget}
          />
        )}
      </div>

      <DialogFooter
        className={cn(
          "w-full shrink-0 flex-row items-stretch sm:space-x-0",
          isCloudBrand
            ? "gap-0 border-t bg-layer-contextual p-0"
            : cn(
                "gap-2 border-t bg-task-dialog-oss px-6 py-4",
                isCancelOnly ? "justify-start" : "justify-end",
              ),
        )}
      >
        {showRetryActions && selectedCount > 0 ? (
          <Button
            type="button"
            className={cn(
              "min-w-0",
              isCloudBrand
                ? "w-1/2 justify-start rounded-none px-4 text-left"
                : "flex-1",
            )}
            disabled={isRetrying || !task}
            onClick={() => void handleRetrySelected()}
          >
            {isRetrying ? "Retrying…" : `Retry selected (${selectedCount})`}
          </Button>
        ) : null}
        {showRetryActions && selectedCount === 0 ? (
          <Button
            type="button"
            className={cn(
              "min-w-0",
              isCloudBrand
                ? "w-1/2 justify-start rounded-none px-4 text-left"
                : "flex-1",
            )}
            disabled={isRetrying || !task}
            onClick={() => void handleRetryAll()}
          >
            {isRetrying ? "Retrying…" : "Retry all"}
          </Button>
        ) : null}
        <Button
          type="button"
          variant={isCloudBrand && isCancelOnly ? "default" : "ghost"}
          ignoreTitleCase
          className={cn(
            isCloudBrand
              ? "w-1/2 shrink-0 justify-start rounded-none px-4 text-left"
              : "shrink-0",
            isCloudBrand && showRetryActions && "ml-auto",
          )}
          onClick={onClose}
          disabled={isRetrying}
        >
          {isCancelOnly ? "Close" : "Cancel"}
        </Button>
      </DialogFooter>
    </div>
  );
}

export default function TaskDialog({
  open,
  onOpenChange,
  task_id,
  onClose,
}: TaskDialogProps) {
  const isCloudBrand = useIsCloudBrand();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex h-task-dialog max-h-task-dialog w-task-dialog max-w-task-dialog flex-col gap-0 overflow-hidden p-0 sm:rounded-lg",
          isCloudBrand
            ? "bg-layer-contextual font-ibm-plex-sans"
            : "bg-task-dialog-oss",
        )}
      >
        <TaskDialogContent
          key={task_id}
          open={open}
          task_id={task_id}
          onClose={onClose}
        />
      </DialogContent>
    </Dialog>
  );
}
