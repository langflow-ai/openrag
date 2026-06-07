"use client";

import { useEffect, useState } from "react";
import type { Task, TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import {
  formatDurationEs,
  formatTaskProgress,
  getActiveTaskElapsedSeconds,
  getElapsedSeconds,
  getIngestionHealth,
  getTaskFileEntryForFilename,
} from "@/lib/task-utils";
import { cn } from "@/lib/utils";

const INGESTION_STAGES = [
  "Parseando documento",
  "Generando embeddings",
  "Indexando",
] as const;

interface IngestionProgressCellProps {
  task?: Task | null;
  filename?: string;
  fileEntry?: TaskFileEntry;
  onOpenActivity?: () => void;
  className?: string;
}

export function IngestionProgressCell({
  task,
  filename,
  fileEntry,
  onOpenActivity,
  className,
}: IngestionProgressCellProps) {
  const [stageIndex, setStageIndex] = useState(0);
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setStageIndex((prev) => (prev + 1) % INGESTION_STAGES.length);
      setTick((t) => t + 1);
    }, 30_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => clearInterval(interval);
  }, []);

  const resolvedEntry =
    fileEntry ??
    (task && filename ? getTaskFileEntryForFilename(task, filename) : undefined);

  const elapsedSec = resolvedEntry
    ? getElapsedSeconds(resolvedEntry)
    : task
      ? getActiveTaskElapsedSeconds(task)
      : 0;

  const durationLabel = formatDurationEs(elapsedSec);
  const health = getIngestionHealth(elapsedSec);
  const progress = task ? formatTaskProgress(task) : null;
  const showMultiFile = (task?.total_files ?? 0) > 1;

  const content = (
    <div className={cn("flex flex-col gap-1 min-w-[120px]", className)}>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full w-full rounded-full bg-primary/50 animate-pulse" />
      </div>
      <span className="text-xs text-muted-foreground whitespace-nowrap">
        Procesando{durationLabel ? ` · ${durationLabel}` : ""}
      </span>
      {showMultiFile && progress && (
        <span className="text-[10px] text-muted-foreground">
          {progress.basicEs}
        </span>
      )}
      <span className="text-[10px] text-muted-foreground/80">
        {INGESTION_STAGES[stageIndex]}
      </span>
      {health === "stale" && (
        <span className="text-[10px] text-brand-amber">
          Puede tardar más de lo habitual — revisá Activity
        </span>
      )}
    </div>
  );

  if (onOpenActivity) {
    return (
      <button
        type="button"
        className="text-left w-full h-full py-1 hover:opacity-80 transition"
        aria-label="Ver detalle de ingesta en Activity"
        onClick={onOpenActivity}
      >
        {content}
      </button>
    );
  }

  return content;
}
