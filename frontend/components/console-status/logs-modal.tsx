"use client";

import { RefreshCw, ScrollText } from "lucide-react";
import {
  type LogEntry,
  useComponentLogsQuery,
} from "@/app/api/queries/useComponentLogsQuery";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function logLevelColor(level: string) {
  switch (level.toLowerCase()) {
    case "error":
    case "critical":
      return "text-red-400";
    case "warning":
      return "text-amber-400";
    case "info":
      return "text-sky-400";
    default:
      return "text-zinc-400";
  }
}

interface ComponentLogsModalProps {
  component: string;
  displayName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ComponentLogsModal({
  component,
  displayName,
  open,
  onOpenChange,
}: ComponentLogsModalProps) {
  const { data, isLoading, isError, error, refetch, isFetching } =
    useComponentLogsQuery(open ? component : null, 100);

  const entries: LogEntry[] = data?.entries ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "bg-zinc-900 border-zinc-700 text-zinc-100",
          "w-[560px] max-w-[95vw] gap-0 p-0",
        )}
      >
        <DialogHeader className="flex flex-row items-center justify-between pl-4 pr-10 py-3 border-b border-zinc-700/60">
          <div className="flex items-center gap-2">
            <ScrollText size={14} className="text-zinc-400" />
            <DialogTitle className="text-sm font-semibold text-zinc-100">
              {displayName} — Logs
            </DialogTitle>
            {isFetching && (
              <RefreshCw size={11} className="text-zinc-500 animate-spin" />
            )}
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-40"
          >
            Refresh
          </button>
        </DialogHeader>

        <div className="overflow-y-auto scrollbar-hide px-4 py-3 space-y-1.5 max-h-[min(28rem,60vh)]">
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-8 rounded bg-zinc-800/60" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-sm text-red-400">
              {error instanceof Error ? error.message : "Failed to load logs."}
            </p>
          ) : entries.length === 0 ? (
            <p className="text-xs text-zinc-500 italic text-center py-6">
              No log entries recorded yet.
            </p>
          ) : (
            entries.map((entry) => (
              <div
                key={`${entry.timestamp}-${entry.message}`}
                className="rounded bg-zinc-800/50 border border-zinc-700/40 px-2.5 py-1.5"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={cn(
                      "text-[10px] font-semibold uppercase tabular-nums shrink-0",
                      logLevelColor(entry.level),
                    )}
                  >
                    {entry.level}
                  </span>
                  <span className="text-[10px] text-zinc-500 tabular-nums shrink-0">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="text-xs text-zinc-200 break-all">
                    {entry.message}
                  </span>
                </div>
                {entry.detail && (
                  <p className="text-[11px] text-zinc-400 mt-0.5 ml-0 break-all font-mono">
                    {entry.detail}
                  </p>
                )}
              </div>
            ))
          )}
        </div>

        <div className="px-4 py-2 border-t border-zinc-700/60">
          <span className="text-[11px] text-zinc-500">
            {entries.length} entr{entries.length === 1 ? "y" : "ies"} (most
            recent 100)
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
