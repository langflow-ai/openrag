"use client";

import { ArrowDown, ArrowUp, ChevronDown, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { type Task } from "@/contexts/task-context";
import { getFailedFileEntries } from "@/lib/task-utils";
import { formatTaskTimestamp, parseTimestamp } from "@/lib/time-utils";

interface TaskErrorContentProps {
  task: Task;
  mode?: "recent" | "past";
  nowMs?: number;
  showHeader?: boolean;
  defaultExpanded?: boolean;
  expandTrigger?: number;
}

export function TaskErrorContent({
  task,
  mode = "recent",
  nowMs = Date.now(),
  showHeader = true,
  defaultExpanded = false,
  expandTrigger = 0,
}: TaskErrorContentProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  useEffect(() => {
    if (defaultExpanded) {
      setIsExpanded(true);
    }
  }, [defaultExpanded, expandTrigger]);
  const failedEntries = useMemo(() => getFailedFileEntries(task), [task]);

  const failedCount = task.failed_files ?? failedEntries.length;
  const successCount = task.successful_files ?? 0;
  const timestamp =
    parseTimestamp(task.created_at) ?? parseTimestamp(task.updated_at);
  const statusLabel = "INCOMPLETE";
  const statusPillClassName =
    "text-destructive border-failure-pill bg-failure-soft";

  if (failedCount <= 0 && failedEntries.length === 0) {
    return null;
  }

  return (
    <div
      className={
        showHeader
          ? "flex flex-col gap-1 border-t border-muted w-full hover:bg-muted/60 transition-colors px-4 py-2"
          : ""
      }
    >
      {showHeader && (
        <>
          <div className="flex items-center justify-between gap-2 min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <XCircle className="h-5 w-5 text-destructive shrink-0" />
              <p className="text-mmd truncate">
                Task {task.task_id.slice(0, 8)}...
              </p>
            </div>
            {!isExpanded && (
              <p
                className={`text-xs shrink-0 border rounded-full px-2 py-1 ${statusPillClassName}`}
              >
                {statusLabel}
              </p>
            )}
          </div>

          <div className="flex flex-col justify-between gap-1">
            <p className="text-xxs text-muted-foreground whitespace-nowrap leading-4 min-h-4">
              {formatTaskTimestamp(timestamp, mode, nowMs)}
            </p>
          </div>
        </>
      )}

      <Accordion
        type="single"
        collapsible
        className="border-0"
        value={isExpanded ? "failure-log" : undefined}
        onValueChange={(value) => setIsExpanded(Boolean(value))}
      >
        <AccordionItem value="failure-log" className="border-0 rounded-none">
          <AccordionTrigger className="group px-0 py-0 text-sm text-destructive hover:text-destructive/80 transition-colors [&>svg:first-child]:hidden">
            <div className="flex items-center gap-1">
              <span className="text-muted-foreground text-xs">
                {successCount} success,
              </span>
              <span className="text-destructive text-xs">
                {failedCount} failed
              </span>
              <ChevronDown className="h-4 w-4 text-destructive transition-transform group-data-[state=open]:rotate-180" />
            </div>
          </AccordionTrigger>
          <AccordionContent className="pt-2 pb-0">
            <div className="rounded-xl border border-destructive/20 bg-failure-soft p-3">
              <p className="text-xs font-medium text-failure-log mb-2 sticky top-0">
                Failure Log{" "}
                <span className="text-failure-muted">
                  ({failedCount} of {failedCount} pending)
                </span>
              </p>
              <div className="max-h-56 overflow-y-auto flex flex-col gap-2">
                {failedEntries.map(([filePath, fileInfo], index) => {
                  const fileName =
                    fileInfo.filename || filePath.split("/").pop() || filePath;
                  const message =
                    typeof fileInfo.error === "string" && fileInfo.error.trim()
                      ? fileInfo.error.trim()
                      : task.error || "Unknown error";

                  return (
                    <div
                      key={`${task.task_id}-${filePath}-${index}`}
                      className="space-y-1"
                    >
                      <p className="text-xs text-failure-file truncate">
                        {">"} {fileName}
                      </p>
                      <p className="text-xs text-failure-message break-words">
                        {message}
                      </p>
                    </div>
                  );
                })}
              </div>
              {failedCount > 1 && (
                <div className="mt-2 text-[9px] text-failure-scroll/40 flex items-center justify-center gap-1">
                  <div className="flex items-center gap-0">
                    <ArrowUp className="h-2 w-2" />
                    <ArrowDown className="h-2 w-2" />
                  </div>
                  <span>scroll · {failedCount} errors</span>
                </div>
              )}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
