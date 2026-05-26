"use client";

import { Ban, Check, Flag } from "lucide-react";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  analyzeTaskFileIngestionFailure,
  type TaskFileIngestionFailureAnalysis,
} from "@/lib/task-error-display";
import { cn } from "@/lib/utils";

interface TaskDialogFileErrorDetailsProps {
  isCloudBrand: boolean;
  indentClassName?: string;
  fileInfo: TaskFileEntry;
  taskError?: string;
  analysis?: TaskFileIngestionFailureAnalysis;
}

export function TaskDialogFileErrorDetails({
  isCloudBrand,
  indentClassName,
  fileInfo,
  taskError,
  analysis: analysisProp,
}: TaskDialogFileErrorDetailsProps) {
  const analysis =
    analysisProp ?? analyzeTaskFileIngestionFailure(fileInfo, taskError);

  return (
    <div
      className={cn(
        "flex flex-col",
        isCloudBrand
          ? "gap-3 pl-9 pr-4 pb-4"
          : cn(
              "gap-1 border-t border-muted/60 py-2 pr-3",
              indentClassName ?? "pl-[4.75rem]",
            ),
      )}
    >
      <div className="flex flex-col">
        {analysis.pipelineSteps.map((step, index) => {
          const isFailed = step.status === "failed";
          const isLast = index === analysis.pipelineSteps.length - 1;

          return (
            <div key={step.id} className="flex gap-3">
              <div className="flex flex-col items-center">
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

              <div
                className={cn(
                  "min-w-0 flex-1",
                  !isLast && (isCloudBrand ? "pb-3" : "pb-1.5"),
                )}
              >
                <p
                  className={cn(
                    "text-sm",
                    isFailed
                      ? "text-muted-foreground"
                      : "text-muted-foreground/80",
                  )}
                >
                  {step.label}
                </p>
                {isFailed && (
                  <div
                    className={cn(
                      isCloudBrand ? "mt-2 space-y-2" : "mt-1 space-y-1",
                    )}
                  >
                    <p className="whitespace-pre-wrap break-words text-sm text-foreground/90">
                      {analysis.resolvedError}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {analysis.failureSummary}
                    </p>
                    {analysis.componentTags.length > 0 && (
                      <div className="flex flex-wrap items-center gap-2 pt-1">
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
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
