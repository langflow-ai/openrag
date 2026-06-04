"use client";

import * as AccordionPrimitive from "@radix-ui/react-accordion";
import { AlertCircle, ChevronDown, Flag, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { IncidentReporterIcon } from "@/components/icons/incident-reporter-icon";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
} from "@/components/ui/accordion";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { type Task, useTask } from "@/contexts/task-context";
import {
  formatApiComponent,
  resolveTaskFileError,
} from "@/lib/task-error-display";
import {
  getFailedFileCount,
  getFailedFileEntries,
  getSuccessfulFileCount,
  getTaskFileName,
  isCompletedTotalFailure,
  isTerminalFailedTask,
} from "@/lib/task-utils";
import { formatTaskTimestamp, parseTimestamp } from "@/lib/time-utils";
import { cn } from "@/lib/utils";

interface TaskErrorContentProps {
  task: Task;
  mode?: "recent" | "past";
  nowMs?: number;
  showHeader?: boolean;
  defaultExpanded?: boolean;
}

export function TaskErrorContent({
  task,
  mode = "recent",
  nowMs = Date.now(),
  showHeader = true,
  defaultExpanded = false,
}: TaskErrorContentProps) {
  const isCloudBrand = useIsCloudBrand();
  const { openTaskDialog } = useTask();
  const [accordionValue, setAccordionValue] = useState(
    defaultExpanded ? "failed-files" : "",
  );
  const isExpanded = accordionValue === "failed-files";

  const failedEntries = useMemo(() => getFailedFileEntries(task), [task]);

  const failedCount = getFailedFileCount(task);
  const successCount = getSuccessfulFileCount(task);
  const timestamp =
    parseTimestamp(task.created_at) ?? parseTimestamp(task.updated_at);
  const isFailedStatus =
    isTerminalFailedTask(task) || isCompletedTotalFailure(task);
  const statusLabel = isFailedStatus ? "Failed" : "Complete";
  // Pill colors: failed (red) vs partial success (amber/orange), each with IBM tokens or OSS borders.
  const statusPillClassName = cn(
    "shrink-0 rounded-full px-2 py-1 text-xs",
    isFailedStatus
      ? isCloudBrand
        ? "border-0 bg-task-status-failed text-task-status-failed-foreground"
        : "border border-failure-pill bg-failure-soft text-destructive"
      : isCloudBrand
        ? "border-0 bg-task-status-partial text-task-status-partial-foreground"
        : "border border-brand-amber-30 bg-brand-amber-10 text-brand-amber",
  );

  if (failedCount <= 0 && failedEntries.length === 0) {
    return null;
  }

  const ossIconColumn = showHeader && !isCloudBrand;

  const accordionSummary = (
    <div className="flex min-w-0 flex-1 items-center gap-1">
      <span className="text-xs">
        {successCount} success · {failedCount} failed
      </span>
      <ChevronDown className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
    </div>
  );

  const openTaskDialogButton = (
    <button
      type="button"
      aria-label="Open task details"
      className="inline-flex shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
      onClick={() => openTaskDialog(task.task_id)}
    >
      <IncidentReporterIcon className="size-4" />
    </button>
  );

  const accordionHeader = (
    <AccordionPrimitive.Header
      className={cn(
        "flex w-full min-w-0 items-center gap-2",
        ossIconColumn && "gap-2.5",
      )}
    >
      {ossIconColumn ? <div className="size-5 shrink-0" aria-hidden /> : null}
      <AccordionPrimitive.Trigger
        className={cn(
          "group inline-flex min-w-0 flex-1 items-center justify-start gap-1 px-0 py-0 text-sm text-muted-foreground transition-colors hover:text-foreground",
        )}
      >
        {accordionSummary}
      </AccordionPrimitive.Trigger>
      {openTaskDialogButton}
    </AccordionPrimitive.Header>
  );

  return (
    <div
      className={cn(
        "w-full",
        showHeader &&
          cn(
            "py-mmd px-4 transition-colors hover:bg-muted/60",
            isCloudBrand
              ? "border-t border-muted"
              : "rounded-mmd border border-muted",
          ),
        !showHeader && "pt-2",
      )}
    >
      <div className="flex w-full min-w-0 flex-col gap-1">
        {showHeader && (
          <div
            className={cn("flex min-w-0 w-full", ossIconColumn && "gap-2.5")}
          >
            {ossIconColumn &&
              (isFailedStatus ? (
                <XCircle
                  className="size-5 shrink-0 text-destructive"
                  aria-hidden
                />
              ) : (
                <AlertCircle
                  className="size-5 shrink-0 text-brand-amber"
                  aria-hidden
                />
              ))}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex min-w-0 items-center justify-between gap-1.5">
                <p className="text-mmd truncate">
                  Task {task.task_id.slice(0, 8)}...
                </p>
                {!isExpanded && (
                  <p className={statusPillClassName}>{statusLabel}</p>
                )}
              </div>
              <p className="min-h-4 text-xxs leading-4 text-muted-foreground whitespace-nowrap">
                {formatTaskTimestamp(timestamp, mode, nowMs)}
              </p>
            </div>
          </div>
        )}

        <Accordion
          type="single"
          collapsible
          className="w-full rounded-mmd border-0"
          value={accordionValue}
          onValueChange={(value) =>
            setAccordionValue(value === "failed-files" ? "failed-files" : "")
          }
        >
          <AccordionItem value="failed-files" className="border-0 rounded-none">
            {accordionHeader}
            <AccordionContent className="w-full p-0 pt-2">
              <div className="flex w-full flex-col gap-2">
                {failedEntries.map(([filePath, fileInfo], index) => {
                  const fileName = getTaskFileName(filePath, fileInfo);
                  const line = resolveTaskFileError(fileInfo, task.error);
                  const componentCause = formatApiComponent(fileInfo.component);

                  return (
                    <div
                      key={`${task.task_id}-${filePath}-${index}`}
                      className={cn(
                        "task-failed-file-card min-w-0",
                        isCloudBrand
                          ? "flex flex-col items-start gap-2 self-stretch rounded-none rounded-r border-l-[1.5px] border-l-destructive bg-border p-2"
                          : "flex flex-col gap-1 rounded border-destructive/20 bg-failure-soft py-mmd px-4",
                      )}
                    >
                      <p
                        className={cn(
                          "w-full truncate text-xs",
                          isCloudBrand
                            ? "font-normal text-foreground"
                            : "font-semibold text-failure-file",
                        )}
                      >
                        {fileName}
                      </p>
                      <p
                        className={cn(
                          "w-full truncate text-xs",
                          isCloudBrand
                            ? "text-muted-foreground"
                            : "text-failure-message",
                        )}
                        title={line}
                      >
                        {line}
                      </p>
                      {componentCause ? (
                        <div className="flex min-w-0 items-center gap-1">
                          <Flag
                            className="size-3 shrink-0 text-destructive"
                            aria-hidden
                          />
                          <span
                            className={cn(
                              "truncate text-xs",
                              isCloudBrand
                                ? "text-muted-foreground"
                                : "text-failure-component-cause",
                            )}
                          >
                            {componentCause}
                          </span>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  );
}
