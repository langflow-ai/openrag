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
  const fileTypeDisabled = !task || fileTypes.length === 0;
  const showRetryActions = retryableCount > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <TaskDialogHeader
        isCloudBrand={isCloudBrand}
        taskId={task_id}
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
          !isCloudBrand && "px-4",
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
            isCloudBrand={isCloudBrand}
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
          "shrink-0 flex-row items-center gap-2 border-t sm:justify-end",
          isCloudBrand ? "px-6 py-4" : "px-4 py-3",
        )}
      >
        <Button
          type="button"
          variant="ghost"
          className={cn(showRetryActions && "flex-1")}
          onClick={onClose}
          disabled={isRetrying}
        >
          {isCloudBrand ? "Cancel" : "Close"}
        </Button>
        {showRetryActions && selectedCount > 0 ? (
          <Button
            type="button"
            className="flex-1"
            disabled={isRetrying || !task}
            onClick={() => void handleRetrySelected()}
          >
            {isRetrying ? "Retrying…" : `Retry selected (${selectedCount})`}
          </Button>
        ) : null}
        {showRetryActions && selectedCount === 0 ? (
          <Button
            type="button"
            className="flex-1"
            disabled={isRetrying || !task}
            onClick={() => void handleRetryAll()}
          >
            {isRetrying ? "Retrying…" : "Retry all"}
          </Button>
        ) : null}
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] w-[640px] max-w-[640px] flex-col gap-0 overflow-hidden p-0 sm:rounded-lg">
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
