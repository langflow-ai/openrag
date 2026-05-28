"use client";

import { Ban, Check, Flag } from "lucide-react";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import { useIsCloudBrand } from "@/contexts/brand-context";
import {
  analyzeTaskFileIngestionFailure,
  type TaskFileIngestionFailureAnalysis,
} from "@/lib/task-error-display";
import { cn } from "@/lib/utils";

interface TaskDialogFileErrorDetailsProps {
  fileInfo: TaskFileEntry;
  taskError?: string;
  analysis?: TaskFileIngestionFailureAnalysis;
}

export function TaskDialogFileErrorDetails({
  fileInfo,
  taskError,
  analysis: analysisProp,
}: TaskDialogFileErrorDetailsProps) {
  const isCloudBrand = useIsCloudBrand();
  const analysis =
    analysisProp ?? analyzeTaskFileIngestionFailure(fileInfo, taskError);

  return (
    <div
      className={cn(
        isCloudBrand
          ? "pl-task-dialog-error-indent-cloud"
          : "pl-task-dialog-error-indent",
        "pr-4 pb-4",
        isCloudBrand
          ? "flex flex-col gap-3"
          : "flex flex-col gap-1 border-t border-muted/60 py-2 pr-3",
      )}
    >
      <div className="flex flex-col">
        {analysis.pipelineSteps.map((step, index) => {
          const isFailed = step.status === "failed";
          const isLast = index === analysis.pipelineSteps.length - 1;
          const showComponentTags =
            isFailed && analysis.componentTags.length > 0;
          const contentRowCount =
            1 + (isFailed ? 2 + (showComponentTags ? 1 : 0) : 0);

          return (
            <div
              key={step.id}
              className={cn(
                "grid grid-cols-[theme(spacing.4)_minmax(0,1fr)] items-start gap-x-3 gap-y-1",
                isFailed && (isCloudBrand ? "gap-y-2" : "gap-y-1"),
              )}
            >
              <div
                className="flex flex-col items-center"
                style={{ gridRow: `1 / span ${contentRowCount}` }}
              >
                {step.status === "completed" ? (
                  <Check
                    className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400"
                    aria-hidden
                  />
                ) : (
                  <Ban
                    className="h-4 w-4 shrink-0 text-destructive"
                    aria-hidden
                  />
                )}
                {!isLast && (
                  <span
                    className={cn(
                      "my-1 w-px flex-1 min-h-3",
                      step.status === "completed"
                        ? "bg-emerald-500/40"
                        : "bg-destructive/40",
                    )}
                  />
                )}
              </div>

              <p
                className={cn(
                  "col-start-2 text-sm",
                  isFailed
                    ? "text-muted-foreground"
                    : "text-muted-foreground/80",
                  !isLast && (isCloudBrand ? "pb-3" : "pb-1.5"),
                )}
              >
                {step.label}
              </p>

              {isFailed && (
                <>
                  <p className="col-start-2 whitespace-pre-wrap break-words text-sm text-foreground/90">
                    {analysis.resolvedError}
                  </p>
                  <p className="col-start-2 text-xs text-muted-foreground">
                    {analysis.failureSummary}
                  </p>
                  {showComponentTags && (
                    <div className="col-start-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Flag
                        className="size-3 shrink-0 text-destructive"
                        aria-hidden
                      />
                      {analysis.componentTags.map((tag) => (
                        <span
                          key={tag}
                          className="text-xs text-failure-component-cause"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
