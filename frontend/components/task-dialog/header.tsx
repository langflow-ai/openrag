"use client";

import type { Task } from "@/app/api/queries/useGetTasksQuery";
import { DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  ALL_TASK_FILE_TYPES,
  formatTaskFileTypeLabel,
  isTaskInProgressStatus,
  type TaskFileStatusCategory,
} from "@/lib/task-utils";
import { cn } from "@/lib/utils";
import { TaskDialogCategoryChips } from "./category-chips";
import { TaskDialogFilters } from "./filters";

interface TaskDialogHeaderProps {
  taskId: string;
  taskStatus?: Task["status"];
  search: string;
  onSearchChange: (value: string) => void;
  fileType: string;
  onFileTypeChange: (value: string) => void;
  fileTypes: string[];
  statusCategory: string;
  onStatusCategoryChange: (value: string) => void;
  categoryCounts: Record<TaskFileStatusCategory, number> | null;
  filtersDisabled: boolean;
  fileTypeDisabled: boolean;
}

export function TaskDialogHeader({
  taskId,
  taskStatus,
  search,
  onSearchChange,
  fileType,
  onFileTypeChange,
  fileTypes,
  statusCategory,
  onStatusCategoryChange,
  categoryCounts,
  filtersDisabled,
  fileTypeDisabled,
}: TaskDialogHeaderProps) {
  const isCloudBrand = useIsCloudBrand();
  const allTypesLabel = isCloudBrand ? "All categories" : "All file types";
  const fileTypeLabel =
    fileType === ALL_TASK_FILE_TYPES
      ? allTypesLabel
      : formatTaskFileTypeLabel(fileType);
  const titlePrefix =
    taskStatus && isTaskInProgressStatus(taskStatus) ? "Active task" : "Task";

  return (
    <header
      className={cn(
        "shrink-0 flex-none",
        isCloudBrand
          ? "border-b border-border bg-layer-contextual"
          : "border-b-0",
      )}
    >
      <DialogHeader
        className={cn(
          "space-y-0 border-b-0 text-left",
          isCloudBrand
            ? "bg-layer-contextual px-6 pt-4 pb-3"
            : "pt-3 pb-2 pr-12",
        )}
      >
        <DialogTitle
          className={cn(
            "py-2 text-base font-semibold leading-snug",
            !isCloudBrand && "px-4",
          )}
        >
          {titlePrefix} {taskId}
        </DialogTitle>
      </DialogHeader>

      <div
        className={cn(
          "flex flex-col gap-2 border-b-0",
          isCloudBrand ? "bg-layer-contextual gap-3 px-0 pb-4" : "px-4 pb-3",
        )}
      >
        <TaskDialogFilters
          search={search}
          onSearchChange={onSearchChange}
          fileType={fileType}
          onFileTypeChange={onFileTypeChange}
          fileTypes={fileTypes}
          fileTypeLabel={fileTypeLabel}
          searchDisabled={filtersDisabled}
          fileTypeDisabled={fileTypeDisabled}
        />
        <TaskDialogCategoryChips
          counts={categoryCounts}
          statusCategory={statusCategory}
          onStatusCategoryChange={onStatusCategoryChange}
        />
      </div>
    </header>
  );
}
