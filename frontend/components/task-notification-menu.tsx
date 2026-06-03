"use client";

import {
  AlertCircle,
  Bell,
  CheckCircle,
  Clock,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { IncidentReporterIcon } from "@/components/icons/incident-reporter-icon";
import { TaskCollapsibleSection } from "@/components/task-collapsible-section";
import { TaskErrorContent } from "@/components/task-error-content";
import { TaskPanelHeader } from "@/components/task-panel-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useIsCloudBrand } from "@/contexts/brand-context";
import { Task, useTask } from "@/contexts/task-context";
import {
  hasFailedFileEntries,
  isCompletedTotalFailure,
  isTerminalFailedTask,
} from "@/lib/task-utils";
import { parseTimestampMs } from "@/lib/time-utils";
import { cn } from "@/lib/utils";

export function TaskNotificationMenu() {
  const isCloudBrand = useIsCloudBrand();
  const {
    tasks,
    isFetching,
    isMenuOpen,
    isRecentTasksExpanded,
    selectedTaskId,
    selectedTaskTrigger,
    cancelTask,
    closeMenu,
    openTaskDialog,
  } = useTask();
  const [isPastOpen, setIsPastOpen] = useState(true);
  const lastHandledSelectionTriggerRef = useRef(0);

  // Reset section defaults whenever panel is opened.
  useEffect(() => {
    if (isMenuOpen) {
      setIsPastOpen(true);
    }
  }, [isMenuOpen]);

  // Sync local state with context state
  useEffect(() => {
    if (isRecentTasksExpanded) {
      setIsPastOpen(true);
    }
  }, [isRecentTasksExpanded]);
  const activeTasks = tasks.filter(
    (task) =>
      task.status === "pending" ||
      task.status === "running" ||
      task.status === "processing",
  );
  const terminalTasks = useMemo(
    () =>
      tasks
        .filter(
          (task) =>
            task.status === "completed" ||
            task.status === "failed" ||
            task.status === "error",
        )
        .sort((a, b) => {
          const aMs =
            parseTimestampMs(a.updated_at) ??
            parseTimestampMs(a.created_at) ??
            0;
          const bMs =
            parseTimestampMs(b.updated_at) ??
            parseTimestampMs(b.created_at) ??
            0;
          return bMs - aMs;
        }),
    [tasks],
  );
  // Ensure selected task is visible in the past tasks section.
  useEffect(() => {
    if (!selectedTaskId) return;
    if (selectedTaskTrigger <= lastHandledSelectionTriggerRef.current) return;
    lastHandledSelectionTriggerRef.current = selectedTaskTrigger;

    const isInTerminal = terminalTasks.some(
      (task) => task.task_id === selectedTaskId,
    );
    if (isInTerminal) {
      setIsPastOpen(true);
    }
  }, [selectedTaskId, terminalTasks]);

  // Don't render if menu is closed
  if (!isMenuOpen) return null;

  const getTaskIcon = (
    status: Task["status"],
    hasFailedFiles = false,
    isTotalFailure = false,
  ) => {
    switch (status) {
      case "completed":
        if (hasFailedFiles) {
          if (isTotalFailure) {
            return <XCircle className="size-4 text-destructive" />;
          }
          return <AlertCircle className="h-4 w-4 text-brand-amber" />;
        }
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case "failed":
      case "error":
        return <XCircle className="size-4 text-destructive" />;
      case "pending":
        return <Clock className="h-4 w-4 text-yellow-500" />;
      case "running":
      case "processing":
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      default:
        return <Clock className="h-4 w-4 text-gray-500" />;
    }
  };

  const pastTaskRowClass = cn(
    "w-full py-mmd px-4 transition-colors hover:bg-muted/60",
    isCloudBrand ? "border-t border-muted" : "rounded-mmd border border-muted",
  );

  const statusBadgeBase = "shrink-0 rounded-full px-2 py-1 text-xs font-normal";

  const getStatusBadge = (
    status: Task["status"],
    hasFailedFiles = false,
    isTotalFailure = false,
  ) => {
    switch (status) {
      case "completed":
        if (hasFailedFiles && isTotalFailure) {
          return (
            <Badge
              variant="outline"
              className={cn(
                statusBadgeBase,
                isCloudBrand
                  ? "border-0 bg-task-status-failed text-task-status-failed-foreground"
                  : "bg-red-500/10 text-red-500 border-red-500/20",
              )}
            >
              FAILED
            </Badge>
          );
        }
        if (hasFailedFiles) {
          return (
            <Badge
              variant="outline"
              className={cn(
                statusBadgeBase,
                isCloudBrand
                  ? "border-0 bg-task-status-partial text-task-status-partial-foreground"
                  : "bg-brand-amber-10 text-brand-amber border-brand-amber-30",
              )}
            >
              Complete
            </Badge>
          );
        }
        return (
          <Badge
            variant="outline"
            className={cn(
              statusBadgeBase,
              isCloudBrand
                ? "border-0 bg-task-status-complete text-task-status-complete-foreground"
                : "border border-green-500/20 bg-green-500/10 text-green-500",
            )}
          >
            Complete
          </Badge>
        );
      case "failed":
      case "error":
        return (
          <Badge
            variant="outline"
            className={cn(
              statusBadgeBase,
              isCloudBrand
                ? "border-0 bg-task-status-failed text-task-status-failed-foreground"
                : "bg-red-500/10 text-red-500 border-red-500/20",
            )}
          >
            FAILED
          </Badge>
        );
      case "pending":
        return (
          <Badge
            variant="outline"
            className={cn(
              statusBadgeBase,
              "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
            )}
          >
            Pending
          </Badge>
        );
      case "running":
      case "processing":
        return (
          <Badge
            variant="outline"
            className={cn(
              statusBadgeBase,
              "bg-blue-500/10 text-blue-500 border-blue-500/20",
            )}
          >
            Processing
          </Badge>
        );
      default:
        return (
          <Badge
            variant="outline"
            className={cn(
              statusBadgeBase,
              "bg-gray-500/10 text-gray-500 border-gray-500/20",
            )}
          >
            Unknown
          </Badge>
        );
    }
  };

  const formatTaskProgress = (task: Task) => {
    const total = task.total_files || 0;
    const processed = task.processed_files || 0;
    const successful = task.successful_files || 0;
    const failed = task.failed_files || 0;
    const running = task.running_files || 0;
    const pending = task.pending_files || 0;

    if (total > 0) {
      return {
        basic: `${processed}/${total} files`,
        detailed: {
          total,
          processed,
          successful,
          failed,
          running,
          pending,
          remaining: total - processed,
        },
      };
    }
    return null;
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds || seconds < 0) return null;

    if (seconds < 60) {
      return `${Math.round(seconds)}s`;
    } else if (seconds < 3600) {
      const mins = Math.floor(seconds / 60);
      const secs = Math.round(seconds % 60);
      return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
    } else {
      const hours = Math.floor(seconds / 3600);
      const mins = Math.floor((seconds % 3600) / 60);
      return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
    }
  };

  const formatRelativeTime = (dateString: string) => {
    // Handle different timestamp formats
    let date: Date;

    // If it's a number (Unix timestamp), convert it
    if (/^\d+$/.test(dateString)) {
      const timestamp = parseInt(dateString);
      // If it looks like seconds (less than 10^13), convert to milliseconds
      date = new Date(timestamp < 10000000000 ? timestamp * 1000 : timestamp);
    }
    // If it's a decimal number (Unix timestamp with decimals)
    else if (/^\d+\.\d+$/.test(dateString)) {
      const timestamp = parseFloat(dateString);
      // Convert seconds to milliseconds
      date = new Date(timestamp * 1000);
    }
    // Otherwise, try to parse as ISO string or other date format
    else {
      date = new Date(dateString);
    }

    // Check if date is valid
    if (isNaN(date.getTime())) {
      console.warn("Invalid date format:", dateString);
      return "Unknown time";
    }

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMinutes = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMinutes < 1) return "Just now";
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <div
      className={cn("h-full bg-background", isCloudBrand && "ibm-tasks-panel")}
    >
      <div className="flex flex-col h-full">
        <TaskPanelHeader
          activeCount={activeTasks.length}
          isFetching={isFetching}
          onClose={closeMenu}
        />

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Active Tasks */}
          {activeTasks.length > 0 && (
            <div className="flex flex-col gap-2 p-4">
              <h4 className="text-sm font-medium text-muted-foreground">
                Active Tasks
              </h4>
              {activeTasks.map((task) => {
                const progress = formatTaskProgress(task);
                const hasFailedFiles = hasFailedFileEntries(task);
                const showCancel =
                  task.status === "pending" ||
                  task.status === "running" ||
                  task.status === "processing";
                const showTaskIcon =
                  !isCloudBrand ||
                  task.status !== "completed" ||
                  hasFailedFiles;

                return (
                  <Card
                    key={task.task_id}
                    className="bg-card/50 border-0 shadow-none py-mmd px-4"
                  >
                    <CardHeader className="p-0 pb-2">
                      <div className="flex items-center justify-between gap-2">
                        <CardTitle className="text-sm flex min-w-0 flex-1 items-center gap-2">
                          {showTaskIcon &&
                            getTaskIcon(
                              task.status,
                              hasFailedFiles,
                              isCompletedTotalFailure(task),
                            )}
                          Task {task.task_id.substring(0, 8)}...
                        </CardTitle>
                        <button
                          type="button"
                          aria-label="Open task details"
                          className="inline-flex shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
                          onClick={() => openTaskDialog(task.task_id)}
                        >
                          <IncidentReporterIcon className="size-4" />
                        </button>
                      </div>
                      <CardDescription className="text-xs">
                        Started {formatRelativeTime(task.created_at)}
                        {formatDuration(task.duration_seconds) && (
                          <span className="ml-2 text-muted-foreground">
                            • {formatDuration(task.duration_seconds)}
                          </span>
                        )}
                      </CardDescription>
                    </CardHeader>
                    {(progress || showCancel) && (
                      <CardContent className="p-0 pt-0">
                        {progress && (
                          <div className="space-y-2">
                            <div className="text-xs text-muted-foreground">
                              Progress: {progress.basic}
                            </div>
                            {progress.detailed && (
                              <div className="grid grid-cols-2 gap-2 text-xs">
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                                  <span className="text-green-600">
                                    {progress.detailed.successful} success
                                  </span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 bg-red-500 rounded-full"></div>
                                  <span className="text-red-600">
                                    {progress.detailed.failed} failed
                                  </span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                                  <span className="text-blue-600">
                                    {progress.detailed.running} running
                                  </span>
                                </div>
                                <div className="flex items-center gap-1">
                                  <div className="w-2 h-2 bg-yellow-500 rounded-full"></div>
                                  <span className="text-yellow-600">
                                    {progress.detailed.pending} pending
                                  </span>
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                        {showCancel && (
                          <div
                            className={`flex justify-end ${progress ? "mt-3" : ""}`}
                          >
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => cancelTask(task.task_id)}
                              className="h-7 px-3 text-xs"
                              title="Cancel task"
                            >
                              <X className="h-3 w-3 mr-1" />
                              Cancel
                            </Button>
                          </div>
                        )}
                        {hasFailedFiles && (
                          <div className="mt-3">
                            <TaskErrorContent
                              key={
                                selectedTaskId === task.task_id
                                  ? `${task.task_id}-${selectedTaskTrigger}`
                                  : task.task_id
                              }
                              task={task}
                              mode="recent"
                              showHeader={false}
                              defaultExpanded={selectedTaskId === task.task_id}
                            />
                          </div>
                        )}
                      </CardContent>
                    )}
                  </Card>
                );
              })}
            </div>
          )}

          {/* Past Tasks */}
          <div>
            <TaskCollapsibleSection
              title="Past Tasks"
              items={terminalTasks}
              isOpen={isPastOpen}
              onToggle={() => setIsPastOpen((prev) => !prev)}
              emptyText="No past tasks."
              containerClassName=""
              contentClassName={cn(
                "flex flex-col transition-all duration-200",
                isCloudBrand
                  ? "p-0 [&>*:last-child]:border-b [&>*:last-child]:border-muted"
                  : "gap-2 p-4 pt-2",
              )}
              renderItem={(task) => {
                const progress = formatTaskProgress(task);
                const hasFailedFiles = hasFailedFileEntries(task);
                const isTotalFailure = isCompletedTotalFailure(task);
                const shouldExpandDetails = selectedTaskId === task.task_id;

                // Same full card as total failure; partial only differs inside (Complete pill / amber icon).
                if (
                  isTerminalFailedTask(task) ||
                  isTotalFailure ||
                  hasFailedFiles
                ) {
                  return (
                    <TaskErrorContent
                      key={
                        shouldExpandDetails
                          ? `${task.task_id}-${selectedTaskTrigger}`
                          : task.task_id
                      }
                      task={task}
                      mode="past"
                      defaultExpanded={shouldExpandDetails}
                    />
                  );
                }

                return (
                  <div key={task.task_id} className={pastTaskRowClass}>
                    <div className="flex items-start gap-3">
                      {!isCloudBrand && getTaskIcon(task.status)}
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium truncate">
                          Task {task.task_id.substring(0, 8)}...
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {formatRelativeTime(task.updated_at)}
                          {formatDuration(task.duration_seconds) && (
                            <span className="ml-2">
                              • {formatDuration(task.duration_seconds)}
                            </span>
                          )}
                        </div>
                        {task.status === "completed" && progress?.detailed && (
                          <div className="text-xs text-muted-foreground">
                            {progress.detailed.successful} success,{" "}
                            {progress.detailed.failed} failed
                            {(progress.detailed.running || 0) > 0 && (
                              <span>, {progress.detailed.running} running</span>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="self-start pt-0.5">
                        {getStatusBadge(task.status)}
                      </div>
                    </div>
                  </div>
                );
              }}
            />
          </div>

          {/* Empty State */}
          {activeTasks.length === 0 && terminalTasks.length === 0 && (
            <div className="p-8 text-center">
              <Bell className="h-12 w-12 text-muted-foreground/50 mx-auto mb-4" />
              <h4 className="text-sm font-medium text-muted-foreground mb-2">
                No tasks yet
              </h4>
              <p className="text-xs text-muted-foreground">
                Task notifications will appear here when you upload files or
                sync connectors.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
