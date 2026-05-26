"use client";

import { ArrowUpAZ, ChevronDown, FileText } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import type { Task } from "@/contexts/task-context";
import { analyzeTaskFileIngestionFailure } from "@/lib/task-error-display";
import {
  getTaskFileDialogStatusLabel,
  getTaskFileName,
  isTaskFileFailed,
  type TaskFileNameSort,
} from "@/lib/task-utils";
import { cn } from "@/lib/utils";
import { TaskDialogFileErrorDetails } from "./file-error-details";

const OSS_ERROR_INDENT = "pl-9";

type TaskDialogFileListTab = "task-ingestions" | "retry-ingestions";

interface TaskDialogFileListProps {
  isCloudBrand: boolean;
  task: Task;
  entries: Array<[string, TaskFileEntry]>;
  totalSourceCount: number;
  totalSourceCountAll?: number;
  nameSort: TaskFileNameSort;
  onToggleNameSort: () => void;
  expandedPath: string | null;
  onExpandedPathChange: (path: string | null) => void;
  /** Retry-ingestion row count; tab is shown only when greater than zero. */
  retryIngestionCount?: number;
}

export function TaskDialogFileList({
  isCloudBrand,
  task,
  entries,
  totalSourceCount,
  totalSourceCountAll,
  nameSort,
  onToggleNameSort,
  expandedPath,
  onExpandedPathChange,
  retryIngestionCount = 0,
}: TaskDialogFileListProps) {
  const [activeTab, setActiveTab] =
    useState<TaskDialogFileListTab>("task-ingestions");

  const showRetryIngestionsTab = retryIngestionCount > 0;

  useEffect(() => {
    if (!showRetryIngestionsTab && activeTab === "retry-ingestions") {
      setActiveTab("task-ingestions");
    }
  }, [showRetryIngestionsTab, activeTab]);

  const analysisByPath = useMemo(() => {
    const map = new Map<
      string,
      ReturnType<typeof analyzeTaskFileIngestionFailure>
    >();
    for (const [filePath, fileInfo] of entries) {
      if (isTaskFileFailed(fileInfo)) {
        map.set(
          filePath,
          analyzeTaskFileIngestionFailure(fileInfo, task.error),
        );
      }
    }
    return map;
  }, [entries, task.error]);

  if (entries.length === 0) {
    return (
      <p
        className={cn(
          "text-center text-sm text-muted-foreground",
          isCloudBrand ? "py-6" : "px-4 py-4",
        )}
      >
        No files match your filters.
      </p>
    );
  }

  const containerClass = cn(
    "flex min-h-0 flex-1 flex-col overflow-hidden",
    isCloudBrand ? "rounded-md border" : "border-b border-muted",
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
              ? "rounded-none rounded-t-lg bg-muted text-foreground"
              : "rounded-none bg-transparent text-muted-foreground hover:text-foreground",
          ),
    );
  };

  const listScrollClass = "min-h-0 flex-1 overflow-y-auto overscroll-contain";

  const fileRows = entries.map(([filePath, fileInfo]) => {
    const fileName = getTaskFileName(filePath, fileInfo);
    const failed = isTaskFileFailed(fileInfo);
    const analysis = analysisByPath.get(filePath);
    const rowStatusLabel = failed
      ? (analysis?.rowStatusLabel ?? "Failed")
      : getTaskFileDialogStatusLabel(fileInfo, task.error);
    const isExpanded = expandedPath === filePath;

    return (
      <div
        key={filePath}
        className={cn(
          "border-b last:border-b-0",
          isCloudBrand ? "border-border" : "border-muted",
        )}
      >
        <div
          className={cn(
            "grid min-h-10 grid-cols-[auto_1fr_auto] items-center gap-3",
            isCloudBrand ? "px-4 hover:bg-muted/40" : "px-3 hover:bg-muted/30",
          )}
        >
          {failed ? (
            <button
              type="button"
              aria-label={isExpanded ? "Collapse error" : "Expand error"}
              aria-expanded={isExpanded}
              onClick={() => onExpandedPathChange(isExpanded ? null : filePath)}
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
            {rowStatusLabel}
          </span>
        </div>

        {failed && isExpanded && analysis && (
          <TaskDialogFileErrorDetails
            isCloudBrand={isCloudBrand}
            indentClassName={!isCloudBrand ? OSS_ERROR_INDENT : ""}
            fileInfo={fileInfo}
            taskError={task.error}
            analysis={analysis}
          />
        )}
      </div>
    );
  });

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

      {isTabActive("task-ingestions") ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div
            className={cn(
              "flex min-h-10 shrink-0 items-center gap-1 bg-muted text-sm font-medium text-muted-foreground",
              isCloudBrand ? "px-4" : "px-3",
            )}
          >
            <button
              type="button"
              className="inline-flex items-center gap-1 hover:text-foreground"
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
          </div>
          <div
            id="task-dialog-panel-task-ingestions"
            role="tabpanel"
            aria-labelledby="task-dialog-tab-task-ingestions"
            className={listScrollClass}
          >
            {fileRows}
          </div>
        </div>
      ) : (
        <div
          id="task-dialog-panel-retry-ingestions"
          role="tabpanel"
          aria-labelledby="task-dialog-tab-retry-ingestions"
          className={cn("flex min-h-0 flex-1 flex-col", listScrollClass)}
          aria-hidden={!showRetryIngestionsTab}
        />
      )}
    </div>
  );
}
