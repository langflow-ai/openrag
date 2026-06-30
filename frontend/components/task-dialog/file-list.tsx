"use client";

import { ArrowUpAZ, ChevronDown, FileText } from "lucide-react";
import { useMemo, useState } from "react";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import { useIsCloudBrand } from "@/contexts/brand-context";
import type { Task } from "@/contexts/task-context";
import { analyzeTaskFileIngestionFailure } from "@/lib/task-error-display";
import {
  getTaskFileDialogStatusLabel,
  getTaskFileName,
  isTaskFileFailed,
  isTaskFileRetryable,
  type TaskFileNameSort,
} from "@/lib/task-utils";
import { cn } from "@/lib/utils";
import { TaskDialogFileErrorDetails } from "./file-error-details";

type TaskDialogFileListTab = "task-ingestions" | "retry-ingestions";

interface TaskDialogFileListProps {
  task: Task;
  entries: Array<[string, TaskFileEntry]>;
  retryIngestionEntries: Array<[string, TaskFileEntry]>;
  totalSourceCount: number;
  totalSourceCountAll?: number;
  nameSort: TaskFileNameSort;
  onToggleNameSort: () => void;
  expandedPath: string | null;
  onExpandedPathChange: (path: string | null) => void;
  retryIngestionCount?: number;
  selectablePaths: string[];
  selectedPaths: Set<string>;
  allSelectableSelected: boolean;
  onToggleSelectedPath: (filePath: string) => void;
  onToggleSelectAllVisible: () => void;
  allRetryIngestionsSelected: boolean;
  onToggleSelectAllRetryIngestions: () => void;
  selectedCount: number;
  retryIngestionSelectedCount: number;
  retryingTarget?: "all" | "selected" | string | null;
}

export function TaskDialogFileList({
  task,
  entries,
  retryIngestionEntries,
  totalSourceCount,
  totalSourceCountAll,
  nameSort,
  onToggleNameSort,
  expandedPath,
  onExpandedPathChange,
  retryIngestionCount = 0,
  selectablePaths,
  selectedPaths,
  allSelectableSelected,
  onToggleSelectedPath,
  onToggleSelectAllVisible,
  allRetryIngestionsSelected,
  onToggleSelectAllRetryIngestions,
  selectedCount,
  retryIngestionSelectedCount,
  retryingTarget = null,
}: TaskDialogFileListProps) {
  const isCloudBrand = useIsCloudBrand();
  const [activeTab, setActiveTab] =
    useState<TaskDialogFileListTab>("task-ingestions");

  const showRetryIngestionsTab = retryIngestionCount > 0;

  if (!showRetryIngestionsTab && activeTab === "retry-ingestions") {
    setActiveTab("task-ingestions");
  }

  const analysisByPath = useMemo(() => {
    const map = new Map<
      string,
      ReturnType<typeof analyzeTaskFileIngestionFailure>
    >();
    const allEntries = [...entries, ...retryIngestionEntries];
    const seen = new Set<string>();
    for (const [filePath, fileInfo] of allEntries) {
      if (seen.has(filePath)) continue;
      seen.add(filePath);
      if (isTaskFileFailed(fileInfo)) {
        map.set(
          filePath,
          analyzeTaskFileIngestionFailure(fileInfo, task.error),
        );
      }
    }
    return map;
  }, [entries, retryIngestionEntries, task.error]);

  const containerClass = cn(
    "flex min-h-0 flex-1 flex-col overflow-hidden",
    isCloudBrand
      ? "rounded-md border-x border-b bg-layer-contextual"
      : "border-b border-muted bg-task-dialog-oss",
  );

  const taskIngestionsTabCount =
    totalSourceCountAll != null && totalSourceCountAll > totalSourceCount
      ? `${totalSourceCount} of ${totalSourceCountAll}`
      : String(totalSourceCount);

  const isTabActive = (tab: TaskDialogFileListTab) => activeTab === tab;

  const tabTriggerClass = (tab: TaskDialogFileListTab) => {
    const isActive = isTabActive(tab);
    return cn(
      "inline-flex w-fit max-w-fit min-h-10 shrink-0 items-center px-4 text-sm font-medium transition-colors",
      isCloudBrand
        ? cn(
            "rounded-none border-0 border-b-2",
            isActive
              ? "border-[var(--border-border-interactive)] bg-muted text-foreground"
              : "border-transparent bg-transparent text-muted-foreground hover:border-[var(--border-border-interactive)]",
          )
        : cn(
            "border-0",
            isActive
              ? "rounded-none rounded-t-lg bg-task-dialog-oss-selected text-foreground"
              : "rounded-none bg-transparent text-muted-foreground hover:text-foreground",
          ),
    );
  };

  const listScrollClass = "min-h-0 flex-1 overflow-y-auto overscroll-contain";

  const rowGridClass =
    "grid min-h-10 grid-cols-[auto_auto_1fr_auto] items-center gap-3";

  const renderFileRows = (listEntries: Array<[string, TaskFileEntry]>) =>
    listEntries.map(([filePath, fileInfo]) => {
      const fileName = getTaskFileName(filePath, fileInfo);
      const failed = isTaskFileFailed(fileInfo);
      const analysis = analysisByPath.get(filePath);
      const rowStatusLabel = failed
        ? (analysis?.rowStatusLabel ?? "Failed")
        : getTaskFileDialogStatusLabel(fileInfo, task.error);
      const isExpanded = expandedPath === filePath;
      const retryable = isTaskFileRetryable(fileInfo);
      const isSelected = selectedPaths.has(filePath);
      const isRowRetrying =
        retryingTarget === "all" ||
        retryingTarget === filePath ||
        (retryingTarget === "selected" && isSelected);
      const retryAttempts = fileInfo.retry_count ?? 0;
      const statusLabel =
        retryable && retryAttempts > 0
          ? `${rowStatusLabel} · Retry ${retryAttempts}`
          : rowStatusLabel;

      return (
        <div
          key={filePath}
          className={cn(
            "border-b last:border-b-0",
            isCloudBrand ? "border-border" : "border-muted",
            isSelected && (isCloudBrand ? "bg-muted" : "bg-muted/30"),
          )}
        >
          <div
            className={cn(
              rowGridClass,
              isCloudBrand ? "px-4 hover:bg-muted" : "px-3 hover:bg-muted/30",
              isSelected &&
                (isCloudBrand ? "hover:bg-muted" : "hover:bg-muted/40"),
            )}
          >
            {retryable ? (
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 rounded border border-input accent-primary"
                checked={isSelected}
                disabled={isRowRetrying}
                aria-label={`Select ${fileName}`}
                onChange={() => onToggleSelectedPath(filePath)}
              />
            ) : (
              <span className="h-4 w-4 shrink-0" aria-hidden />
            )}
            {failed ? (
              <button
                type="button"
                aria-label={isExpanded ? "Collapse error" : "Expand error"}
                aria-expanded={isExpanded}
                onClick={() =>
                  onExpandedPathChange(isExpanded ? null : filePath)
                }
                className="inline-flex h-5 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
              >
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    isExpanded && "rotate-180",
                  )}
                />
              </button>
            ) : (
              <span className="h-5 w-5" aria-hidden />
            )}
            <button
              type="button"
              className={cn(
                "flex min-w-0 items-center gap-2 text-left",
                failed && "cursor-pointer",
              )}
              onClick={() => {
                if (!failed) return;
                onExpandedPathChange(isExpanded ? null : filePath);
              }}
              disabled={!failed}
            >
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span
                className={cn("truncate text-sm", failed && "text-foreground")}
                title={fileName}
              >
                {fileName}
              </span>
            </button>
            <span
              className={cn(
                "shrink-0 text-sm",
                failed
                  ? "text-destructive"
                  : rowStatusLabel === "Complete"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-muted-foreground",
              )}
            >
              {statusLabel}
            </span>
          </div>

          {failed && isExpanded && analysis && (
            <TaskDialogFileErrorDetails
              fileInfo={fileInfo}
              taskError={task.error}
              analysis={analysis}
            />
          )}
        </div>
      );
    });

  const renderListHeader = ({
    showSelectAll,
    allSelected,
    onToggleSelectAll,
    selectedLabel,
  }: {
    showSelectAll: boolean;
    allSelected: boolean;
    onToggleSelectAll: () => void;
    selectedLabel?: string;
  }) => (
    <div
      className={cn(
        "flex min-h-10 shrink-0 items-center gap-3 text-sm font-medium text-muted-foreground",
        isCloudBrand ? "bg-muted px-4" : "bg-task-dialog-oss-selected px-3",
      )}
    >
      {showSelectAll ? (
        <input
          type="checkbox"
          className="h-4 w-4 shrink-0 rounded border border-input accent-primary"
          checked={allSelected}
          disabled={retryingTarget != null}
          aria-label="Select all retryable files"
          onChange={onToggleSelectAll}
        />
      ) : null}
      <button
        type="button"
        className="inline-flex min-w-0 flex-1 items-center gap-1 hover:text-foreground"
        onClick={onToggleNameSort}
      >
        <span>Source</span>
        <ArrowUpAZ
          className={cn(
            "h-3.5 w-3.5",
            isCloudBrand ? "opacity-70" : "opacity-50",
            nameSort === "desc" && "rotate-180",
          )}
          aria-hidden
        />
        <span className="sr-only">
          Sort by name {nameSort === "asc" ? "A to Z" : "Z to A"}
        </span>
      </button>
      {selectedLabel ? (
        <span className="shrink-0 text-xs tabular-nums">{selectedLabel}</span>
      ) : null}
    </div>
  );

  const renderEmptyPanel = (message: string) => (
    <p
      className={cn(
        "text-center text-sm text-muted-foreground",
        isCloudBrand ? "py-6" : "px-4 py-4",
      )}
    >
      {message}
    </p>
  );

  return (
    <div className={containerClass}>
      <div
        className="flex w-fit max-w-fit shrink-0 items-end gap-1 p-0"
        role="tablist"
        aria-label="Task file views"
      >
        <button
          type="button"
          role="tab"
          id="task-dialog-tab-task-ingestions"
          aria-selected={isTabActive("task-ingestions")}
          aria-controls="task-dialog-panel-task-ingestions"
          className={tabTriggerClass("task-ingestions")}
          onClick={() => setActiveTab("task-ingestions")}
        >
          Task ingestions ({taskIngestionsTabCount})
        </button>
        {showRetryIngestionsTab && (
          <button
            type="button"
            role="tab"
            id="task-dialog-tab-retry-ingestions"
            aria-selected={isTabActive("retry-ingestions")}
            aria-controls="task-dialog-panel-retry-ingestions"
            className={tabTriggerClass("retry-ingestions")}
            onClick={() => setActiveTab("retry-ingestions")}
          >
            Retry ingestions ({retryIngestionCount})
          </button>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {isTabActive("task-ingestions")
          ? renderListHeader({
              showSelectAll: selectablePaths.length > 0,
              allSelected: allSelectableSelected,
              onToggleSelectAll: onToggleSelectAllVisible,
              selectedLabel:
                selectedCount > 0 ? `${selectedCount} selected` : undefined,
            })
          : null}
        {isTabActive("retry-ingestions")
          ? renderListHeader({
              showSelectAll: true,
              allSelected: allRetryIngestionsSelected,
              onToggleSelectAll: onToggleSelectAllRetryIngestions,
              selectedLabel:
                retryIngestionSelectedCount > 0
                  ? `${retryIngestionSelectedCount} selected`
                  : undefined,
            })
          : null}
        <div
          id="task-dialog-panel-task-ingestions"
          role="tabpanel"
          aria-labelledby="task-dialog-tab-task-ingestions"
          hidden={!isTabActive("task-ingestions")}
          className={listScrollClass}
        >
          {entries.length === 0
            ? renderEmptyPanel("No files match your filters.")
            : renderFileRows(entries)}
        </div>
        {showRetryIngestionsTab ? (
          <div
            id="task-dialog-panel-retry-ingestions"
            role="tabpanel"
            aria-labelledby="task-dialog-tab-retry-ingestions"
            hidden={!isTabActive("retry-ingestions")}
            className={listScrollClass}
          >
            {retryIngestionEntries.length === 0
              ? renderEmptyPanel("No retryable files in this task.")
              : renderFileRows(retryIngestionEntries)}
          </div>
        ) : null}
      </div>
    </div>
  );
}
