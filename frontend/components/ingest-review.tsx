"use client";

import {
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  FileIcon,
  Loader2,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import {
  type DoclingPreviewResponse,
  type IndexProofChunk,
  useDoclingPreviewQuery,
  useIndexProofQuery,
} from "@/app/api/queries/useIngestPreviewQuery";
import {
  DoclingParseViewer,
  DoclingTextPreview,
} from "@/components/docling-preview";
import { FileChunksPanel } from "@/components/file-chunks-panel";
import { IngestPreviewAutoOpenControl } from "@/components/ingest-preview-auto-open-control";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { useTask } from "@/contexts/task-context";
import {
  type IngestPreviewSettings,
  useIngestPreviewSettings,
} from "@/hooks/use-ingest-preview-settings";
import {
  doclingHasPageImages,
  matchChunkToDoclingItems,
  summarizeChunkPages,
} from "@/lib/ingest-preview";
import {
  buildSampleDemoDocument,
  SAMPLE_DEMO_CHUNKS,
  SAMPLE_DEMO_FILENAME,
  SAMPLE_DEMO_STATS,
} from "@/lib/ingest-preview-demo";
import { cn } from "@/lib/utils";

/** Client-only walkthrough phases for “Run a sample ingest” (nothing is uploaded). */
function useDemoPreviewPhase(enabled: boolean): number {
  const [phase, setPhase] = useState(0);
  const [prevEnabled, setPrevEnabled] = useState(enabled);

  // Reset inline when `enabled` flips so we never paint a stale phase.
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  if (enabled !== prevEnabled) {
    setPrevEnabled(enabled);
    setPhase(0);
  }

  useEffect(() => {
    if (!enabled) return;
    const delays = [500, 1100, 1700, 2300];
    const timers = delays.map((ms, index) =>
      setTimeout(() => setPhase(index + 1), ms),
    );
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  }, [enabled]);
  return phase;
}

function previewFrameClass(expanded: boolean): string {
  return cn(
    "overflow-auto rounded-md bg-background",
    // Fixed height in dialog mode so skeleton → Docling swap does not jump.
    expanded
      ? "h-full min-h-0 max-h-none"
      : "h-[420px] min-h-[420px] max-h-[420px]",
  );
}

function isFileEntryFailed(entry?: TaskFileEntry): boolean {
  return entry?.status === "failed" || entry?.status === "error";
}

/** A file is viewable once Docling has finished (phase past docling). */
function isPreviewReady(entry?: TaskFileEntry): boolean {
  return entry?.phase === "langflow" || entry?.phase === "complete";
}

// --- Left column: the original document -------------------------------------

function SkeletonChunk({
  label,
  lines,
  active = false,
  className,
}: {
  label: string;
  lines: ReadonlyArray<{ id: string; width: string }>;
  /** Emphasized chunk (thicker border + stronger badge), matching the design mock. */
  active?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative rounded-md border-dashed bg-transparent p-3 pt-4",
        active
          ? "border-2 border-sky-500 dark:border-sky-400"
          : "border border-sky-300/70 dark:border-sky-500/35",
        className,
      )}
    >
      <span
        className={cn(
          "absolute -top-2.5 left-2 rounded-full px-2 py-0.5 text-[10px] font-medium leading-none text-white",
          active ? "bg-sky-500" : "bg-sky-400/80 dark:bg-sky-500/70",
        )}
      >
        {label}
      </span>
      <div className="flex flex-col gap-2">
        {lines.map((line) => (
          <Skeleton
            key={line.id}
            className={cn(
              "h-2 rounded-full bg-muted-foreground/20 dark:bg-muted-foreground/25",
              line.width,
            )}
          />
        ))}
      </div>
    </div>
  );
}

/** Placeholder DocPage layout while Docling parse preview is loading. */
function DoclingDocSkeleton({ expanded = false }: { expanded?: boolean }) {
  return (
    <div
      className={cn(
        previewFrameClass(expanded),
        "bg-muted/40 p-3",
        expanded && "min-h-0 flex-1",
      )}
      data-testid="ingest-review-doc-skeleton"
      aria-busy="true"
      aria-label="Loading document layout"
    >
      <div className="min-h-full rounded-lg border border-border/60 bg-background p-4 shadow-sm space-y-5">
        <SkeletonChunk
          label="Header"
          lines={[
            { id: "h1", width: "w-3/5" },
            { id: "h2", width: "w-2/5" },
            { id: "h3", width: "w-1/2" },
          ]}
        />
        <SkeletonChunk
          label="Chunk 1"
          active
          lines={[
            { id: "c1a", width: "w-full" },
            { id: "c1b", width: "w-5/6" },
            { id: "c1c", width: "w-full" },
            { id: "c1d", width: "w-4/5" },
            { id: "c1e", width: "w-full" },
            { id: "c1f", width: "w-5/6" },
            { id: "c1g", width: "w-2/3" },
          ]}
        />
        <SkeletonChunk
          label="Chunk 2"
          lines={[
            { id: "c2a", width: "w-full" },
            { id: "c2b", width: "w-5/6" },
            { id: "c2c", width: "w-full" },
            { id: "c2d", width: "w-4/5" },
            { id: "c2e", width: "w-3/5" },
          ]}
        />
        <p className="pt-1 text-right text-xs text-muted-foreground/60">1</p>
      </div>
    </div>
  );
}

function DocumentPane({
  failed,
  failureMessage,
  parsePreview,
  highlightItemRefs,
  fallbackPage,
  highlightText,
  chunkLabel,
  hasChunks,
  expanded = false,
}: {
  failed: boolean;
  failureMessage: string;
  parsePreview: DoclingPreviewResponse | null | undefined;
  highlightItemRefs?: string[];
  fallbackPage?: number | null;
  highlightText?: string;
  chunkLabel?: string;
  hasChunks: boolean;
  expanded?: boolean;
}) {
  const doclingDocument = parsePreview?.document;
  const frameClass = previewFrameClass(expanded);

  if (failed) {
    return (
      <div
        className="flex h-56 flex-col items-center justify-center gap-2 px-4 text-center text-muted-foreground"
        data-testid="ingest-review-failed"
      >
        <p className="text-md font-medium text-destructive">Parsing failed</p>
        <p className="text-xs">{failureMessage}</p>
      </div>
    );
  }

  if (doclingDocument) {
    if (doclingHasPageImages(doclingDocument)) {
      return (
        <div className={cn(frameClass, expanded && "min-h-0 flex-1")}>
          <p className="mb-2 shrink-0 text-xs text-muted-foreground">
            Blue boxes mark parsed text, tables, and figures.
            {hasChunks ? " Click a chunk to focus its region." : null}
          </p>
          <DoclingParseViewer
            doclingDocument={doclingDocument}
            highlightItemRefs={highlightItemRefs}
            fallbackPage={fallbackPage}
            chunkLabel={chunkLabel}
          />
        </div>
      );
    }
    return (
      <div className={cn(frameClass, expanded && "min-h-0 flex-1")}>
        <p className="mb-2 shrink-0 text-xs text-muted-foreground">
          No page image for this format — each region Docling detected is boxed
          and labeled by type.
          {hasChunks ? " Click a chunk to focus its region." : null}
        </p>
        <DoclingTextPreview
          doclingDocument={doclingDocument}
          highlightItemRefs={highlightItemRefs}
          highlightText={highlightText}
          chunkLabel={chunkLabel}
        />
      </div>
    );
  }

  return <DoclingDocSkeleton expanded={expanded} />;
}

// --- Right column: indexing pipeline + chunks -------------------------------

interface PipelineStep {
  id: string;
  done: boolean;
  label: string;
}

function ProofLine({
  done,
  label,
  failed,
  idle,
}: {
  done: boolean;
  label: string;
  failed: boolean;
  idle: boolean;
}) {
  return (
    <li className="flex items-center gap-2.5">
      {failed ? (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-destructive">
          <X className="h-3 w-3 text-destructive-foreground" />
        </span>
      ) : done ? (
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[rgb(0_188_125/0.15)]">
          <Check className="h-3 w-3 text-[rgb(0_188_125)]" strokeWidth={3} />
        </span>
      ) : idle ? (
        <Circle className="h-5 w-5 shrink-0 text-muted-foreground/40" />
      ) : (
        <Loader2 className="h-5 w-5 shrink-0 animate-spin text-blue-500" />
      )}
      <span
        className={cn(
          "text-sm",
          failed
            ? "text-destructive"
            : done
              ? "text-foreground"
              : "text-muted-foreground",
        )}
      >
        {label}
      </span>
    </li>
  );
}

function DemoChunksList({
  chunks,
  showContents,
  chunkSearch,
  selectedChunkIndex,
  onSelectChunk,
  expanded = false,
}: {
  chunks: IndexProofChunk[];
  showContents: boolean;
  chunkSearch: string;
  selectedChunkIndex?: number | null;
  onSelectChunk: (chunk: {
    index: number;
    page: number | null;
    text: string;
  }) => void;
  expanded?: boolean;
}) {
  const needle = chunkSearch.trim().toLowerCase();
  const visible = needle
    ? chunks.filter((chunk) =>
        chunk.text_preview.toLowerCase().includes(needle),
      )
    : chunks;

  if (visible.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No chunks match your search.
      </p>
    );
  }

  return (
    <div
      className={cn(
        "space-y-3 overflow-auto",
        expanded ? "min-h-0 flex-1" : "max-h-72",
      )}
      data-testid="ingest-review-demo-chunks"
    >
      {visible.map((chunk, index) => {
        const chunkIndex = index + 1;
        const selected = selectedChunkIndex === chunkIndex;
        return (
          <button
            key={chunk.chunk_id}
            type="button"
            className={cn(
              "w-full rounded-lg border border-border/50 bg-muted p-2.5 text-left transition-colors hover:border-primary/40",
              selected && "border-primary/60 ring-1 ring-primary/30",
            )}
            onClick={() =>
              onSelectChunk({
                index: chunkIndex,
                page: chunk.page ?? null,
                text: chunk.text_preview,
              })
            }
          >
            <div className="mb-2 flex min-w-0 flex-wrap items-center gap-2">
              <span className="text-xs font-bold">Chunk {chunkIndex}</span>
              <Badge variant="secondary" className="text-xxs">
                {chunk.char_count} chars
              </Badge>
            </div>
            {showContents ? (
              <blockquote className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
                {chunk.text_preview}
              </blockquote>
            ) : (
              <p className="text-xs text-muted-foreground">
                {chunk.page != null ? `page ${chunk.page}` : "chunk"} ·{" "}
                {chunk.char_count} chars
              </p>
            )}
          </button>
        );
      })}
    </div>
  );
}

function IndexPane({
  steps,
  filename,
  showIndexingPipeline,
  showChunkBoundaries,
  showChunkContents,
  failed,
  failedStepIndex,
  failureMessage,
  onViewError,
  awaitingChunks,
  selectedChunkIndex,
  onSelectChunk,
  chunkSearch,
  onChunkSearchChange,
  demoChunks,
  expanded = false,
}: {
  steps: PipelineStep[];
  filename: string | undefined;
  showIndexingPipeline: boolean;
  showChunkBoundaries: boolean;
  showChunkContents: boolean;
  failed: boolean;
  failedStepIndex: number;
  failureMessage: string;
  onViewError?: () => void;
  awaitingChunks: boolean;
  selectedChunkIndex?: number | null;
  onSelectChunk: (chunk: {
    index: number;
    page: number | null;
    text: string;
  }) => void;
  chunkSearch: string;
  onChunkSearchChange: (query: string) => void;
  demoChunks?: IndexProofChunk[];
  expanded?: boolean;
}) {
  const activeStepIndex = failed ? -1 : steps.findIndex((step) => !step.done);

  return (
    <div
      className={cn(
        "flex min-h-[280px] flex-col rounded-lg border border-border/60 bg-muted/30 p-4",
        expanded && "h-full min-h-0",
      )}
    >
      {showIndexingPipeline && (
        <div className="shrink-0">
          <h3 className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Index details
          </h3>
          <ul className="mb-4 space-y-3">
            {steps.map((step, i) => {
              const isFailed = failed && i === failedStepIndex;
              const isActive = !failed && i === activeStepIndex;
              const isIdle =
                (failed && i > failedStepIndex && !step.done) ||
                (!failed && i > activeStepIndex && !step.done);
              return (
                <ProofLine
                  key={step.id}
                  done={step.done && !isFailed}
                  failed={isFailed}
                  idle={isIdle && !isActive}
                  label={isFailed ? failureMessage : step.label}
                />
              );
            })}
          </ul>
        </div>
      )}

      {failed && onViewError && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mb-4 w-full shrink-0"
          data-testid="ingest-review-view-error"
          onClick={onViewError}
        >
          View error details &amp; retry
        </Button>
      )}

      {showIndexingPipeline && showChunkBoundaries && (
        <div className="mb-4 shrink-0 border-t border-border/60" />
      )}

      {showChunkBoundaries && filename && !awaitingChunks && demoChunks && (
        <div className={cn(expanded && "min-h-0 flex-1")}>
          <DemoChunksList
            chunks={demoChunks}
            showContents={showChunkContents}
            chunkSearch={chunkSearch}
            selectedChunkIndex={selectedChunkIndex}
            onSelectChunk={onSelectChunk}
            expanded={expanded}
          />
        </div>
      )}

      {showChunkBoundaries && filename && !awaitingChunks && !demoChunks && (
        <div className={cn(expanded && "min-h-0 flex-1")}>
          <FileChunksPanel
            filename={filename}
            compact
            fillHeight={expanded}
            showContents={showChunkContents}
            selectedChunkIndex={selectedChunkIndex}
            hideSearch
            filterQuery={chunkSearch}
            onFilterQueryChange={onChunkSearchChange}
            onChunkSelect={(chunk) => {
              onSelectChunk({
                index: chunk.index ?? 0,
                page: chunk.page ?? null,
                text: chunk.text,
              });
            }}
          />
        </div>
      )}

      {showChunkBoundaries && awaitingChunks && !failed && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Waiting for chunks…
        </div>
      )}
    </div>
  );
}

// --- File selector ----------------------------------------------------------

interface CarouselFile {
  taskId: string | null;
  filePath: string | null;
  entry?: TaskFileEntry;
  filename: string;
}

function fileSelectionKey(file: CarouselFile): string {
  return `${file.taskId ?? "local"}:${file.filePath ?? file.filename}`;
}

function PreviewFileSelector({
  files,
  activeIndex,
  onSelect,
}: {
  files: CarouselFile[];
  activeIndex: number;
  onSelect: (index: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const listboxId = useId();
  const active = files[activeIndex];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          className="h-auto w-full min-w-0 justify-between gap-2 px-1.5 py-2 font-medium hover:bg-muted/60"
          data-testid="ingest-review-file-selector"
        >
          <span className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate" title={active?.filename}>
              {active?.filename ?? "Select file"}
            </span>
          </span>
          {open ? (
            <ChevronUp className="h-3.5 w-3.5 shrink-0 opacity-50" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="min-w-[260px] w-[var(--radix-popover-trigger-width)] p-0"
        align="start"
      >
        <Command>
          <CommandInput placeholder="Search files…" />
          <CommandList id={listboxId}>
            <CommandEmpty>No files found.</CommandEmpty>
            <CommandGroup>
              {files.map((file, index) => {
                const key = fileSelectionKey(file);
                const failed = isFileEntryFailed(file.entry);
                const ready = !failed && isPreviewReady(file.entry);
                const status = failed
                  ? "failed"
                  : ready
                    ? "ready"
                    : "processing";
                return (
                  <CommandItem
                    key={key}
                    value={key}
                    keywords={[file.filename]}
                    onSelect={() => {
                      onSelect(index);
                      setOpen(false);
                    }}
                    className="min-w-0 gap-2 overflow-hidden"
                  >
                    <Check
                      className={cn(
                        "h-4 w-4 shrink-0",
                        index === activeIndex ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span
                      className="min-w-0 flex-1 truncate"
                      title={file.filename}
                    >
                      {file.filename}
                    </span>
                    <span
                      className={cn(
                        "shrink-0 text-xs",
                        failed
                          ? "text-destructive"
                          : ready
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-muted-foreground",
                      )}
                    >
                      {status}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// --- Content container -------------------------------------------------------

/**
 * Flatten the files of every task into one ordered list. Folder uploads split
 * into several batch tasks, so the review spans them as one continuous set.
 */
function carouselFilesFromTasks(
  tasks: Task[] | undefined,
  taskIds: string[],
): CarouselFile[] {
  if (!tasks || taskIds.length === 0) return [];
  const tasksById = new Map(tasks.map((task) => [task.task_id, task]));
  const files: CarouselFile[] = [];
  for (const id of taskIds) {
    const task = tasksById.get(id);
    if (!task?.files) continue;
    for (const [filePath, entry] of Object.entries(task.files)) {
      files.push({
        taskId: task.task_id,
        filePath,
        entry,
        filename: entry.filename ?? filePath.split("/").pop() ?? filePath,
      });
    }
  }
  return files;
}

const FAILURE_PHASE_TO_STEP: Record<string, number> = {
  parsing: 0,
  file_validation: 0,
  chunking: 1,
  embedding: 2,
  indexing: 3,
};

type ChunkHighlight = {
  index: number;
  page: number | null;
  text: string;
};

function useIngestCompletionToast({
  demo,
  ready,
  completionNotification,
  activeFilename,
  activeSelectionKey,
}: {
  demo: boolean;
  ready: boolean;
  completionNotification: boolean;
  activeFilename: string | undefined;
  activeSelectionKey: string;
}) {
  const notifiedRef = useRef<Set<string> | null>(null);
  if (notifiedRef.current === null) {
    notifiedRef.current = new Set();
  }

  useEffect(() => {
    if (demo || !completionNotification || !ready || !activeFilename) {
      return;
    }
    const key = activeSelectionKey || activeFilename;
    const notified = notifiedRef.current;
    if (!notified || notified.has(key)) return;
    notified.add(key);
    toast.success("Task completed", {
      description: `${activeFilename} is indexed and searchable.`,
    });
  }, [demo, ready, completionNotification, activeFilename, activeSelectionKey]);
}

function useIngestReviewModel({
  taskIds,
  previewFiles,
  demo,
  settingsOverride,
}: {
  taskIds: string[];
  previewFiles?: File[];
  demo: boolean;
  settingsOverride?: IngestPreviewSettings;
}) {
  const { settings: storedSettings, updateSettings } =
    useIngestPreviewSettings();
  const settings = settingsOverride ?? storedSettings;
  const { data: tasks } = useGetTasksQuery({
    enabled: !demo && taskIds.length > 0,
  });
  const demoPhase = useDemoPreviewPhase(demo);
  const demoDocument = useMemo(
    () => (demo ? buildSampleDemoDocument() : null),
    [demo],
  );

  const fromTasks = carouselFilesFromTasks(tasks, taskIds);
  const files: CarouselFile[] =
    fromTasks.length > 0
      ? fromTasks
      : (previewFiles ?? []).length > 0
        ? (previewFiles ?? []).map((file) => ({
            taskId: null,
            filePath: null,
            filename: file.name,
          }))
        : demo
          ? [
              {
                taskId: null,
                filePath: null,
                filename: SAMPLE_DEMO_FILENAME,
              },
            ]
          : [];

  // Stable across task polls / late-arriving folder batches (not a list index).
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selectedIndex = selectedKey
    ? files.findIndex((f) => fileSelectionKey(f) === selectedKey)
    : -1;
  const activeIndex = selectedIndex >= 0 ? selectedIndex : 0;

  const active = files[activeIndex];
  const activeTaskId = demo ? null : (active?.taskId ?? taskIds[0] ?? null);

  const failed = !demo && isFileEntryFailed(active?.entry);
  const activeFilePath = active?.filePath ?? null;

  const { data: liveParsePreview } = useDoclingPreviewQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed,
    activeFilePath,
  );
  const { data: liveIndexProof } = useIndexProofQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed,
    activeFilePath,
  );

  const parsePreview: DoclingPreviewResponse | null | undefined = demo
    ? demoPhase >= 1 && demoDocument
      ? {
          task_id: "demo",
          document: demoDocument,
          stats: SAMPLE_DEMO_STATS,
          expires_at: 0,
          filename: active?.filename,
        }
      : null
    : liveParsePreview;

  const indexProof = demo
    ? {
        ready: demoPhase >= 4,
        chunk_count: demoPhase >= 2 ? SAMPLE_DEMO_CHUNKS.length : 0,
        embedding_dimensions: demoPhase >= 3 ? 1536 : undefined,
        chunks: demoPhase >= 2 ? SAMPLE_DEMO_CHUNKS : [],
      }
    : liveIndexProof;

  const [chunkHighlight, setChunkHighlight] = useState<ChunkHighlight | null>(
    null,
  );
  const [chunkSearch, setChunkSearch] = useState("");
  const activeSelectionKey = active ? fileSelectionKey(active) : "";
  const [prevActiveSelectionKey, setPrevActiveSelectionKey] =
    useState(activeSelectionKey);
  if (activeSelectionKey !== prevActiveSelectionKey) {
    setPrevActiveSelectionKey(activeSelectionKey);
    setChunkHighlight(null);
    setChunkSearch("");
  }

  const showChunks = settings.showChunkBoundaries;
  const { numbering: pageNumbering } = summarizeChunkPages(
    indexProof?.chunks ?? [],
  );

  const doclingMatch = useMemo(() => {
    if (!chunkHighlight) return null;
    return matchChunkToDoclingItems(
      parsePreview?.document,
      { page: chunkHighlight.page, text: chunkHighlight.text },
      pageNumbering,
    );
  }, [chunkHighlight, parsePreview?.document, pageNumbering]);

  const highlightItemRefs = doclingMatch?.itemRefs;
  // Always keep a page fallback for PDF overlays when the chunk has a page —
  // text→item matching is often weak on PDFs, and nested shadow queries need it.
  const fallbackPage =
    chunkHighlight?.page != null
      ? pageNumbering === "zero-based"
        ? chunkHighlight.page + 1
        : chunkHighlight.page
      : null;
  const chunkLabel =
    chunkHighlight != null ? `Chunk ${chunkHighlight.index}` : undefined;

  const doclingFinished = demo ? demoPhase >= 1 : isPreviewReady(active?.entry);
  const layoutReady = Boolean(parsePreview?.document);
  const chunkCount = indexProof?.chunk_count ?? 0;
  const steps: PipelineStep[] = [
    {
      id: "layout",
      done: layoutReady || doclingFinished,
      label: "Reading layout",
    },
    { id: "chunks", done: chunkCount > 0, label: "Creating chunks" },
    {
      id: "embeddings",
      done: Boolean(indexProof?.embedding_dimensions),
      label: "Generating embeddings",
    },
    {
      id: "stored",
      done: Boolean(indexProof?.ready),
      label: demo ? "Ready for retrieval" : "Stored in OpenSearch",
    },
  ];

  const failureMessage =
    active?.entry?.user_facing_message ||
    active?.entry?.error ||
    "Ingestion failed. Please try again.";
  let failedStepIndex = -1;
  if (failed) {
    const failurePhase = active?.entry?.failure_phase;
    if (failurePhase && failurePhase in FAILURE_PHASE_TO_STEP) {
      failedStepIndex = FAILURE_PHASE_TO_STEP[failurePhase];
    } else {
      const firstNotDone = steps.findIndex((s) => !s.done);
      failedStepIndex = firstNotDone === -1 ? steps.length - 1 : firstNotDone;
    }
  }

  const activeFilename = active?.filename;
  useIngestCompletionToast({
    demo,
    ready: Boolean(indexProof?.ready),
    completionNotification: settings.completionNotification,
    activeFilename,
    activeSelectionKey,
  });

  return {
    settings,
    updateSettings,
    files,
    activeIndex,
    setSelectedKey,
    activeTaskId,
    failed,
    parsePreview,
    chunkHighlight,
    setChunkHighlight,
    chunkSearch,
    setChunkSearch,
    showChunks,
    highlightItemRefs,
    fallbackPage,
    chunkLabel,
    chunkCount,
    steps,
    failureMessage,
    failedStepIndex,
    activeFilename,
  };
}

function IngestReviewToolbar({
  files,
  activeIndex,
  activeFilename,
  parsePreview,
  showChunks,
  chunkSearch,
  onSelectFile,
  onChunkSearch,
  onClearChunkSearch,
}: {
  files: CarouselFile[];
  activeIndex: number;
  activeFilename: string | undefined;
  parsePreview: DoclingPreviewResponse | null | undefined;
  showChunks: boolean;
  chunkSearch: string;
  onSelectFile: (index: number) => void;
  onChunkSearch: (query: string) => void;
  onClearChunkSearch: () => void;
}) {
  const canNavigate = files.length > 1;

  return (
    <div className="-mx-4 shrink-0 grid items-center gap-3 border-t border-b border-border px-4 lg:grid-cols-2 lg:gap-0">
      <div className="flex min-w-0 items-center gap-x-4 lg:pr-4">
        {canNavigate ? (
          <div className="min-w-0 flex-1">
            <PreviewFileSelector
              files={files}
              activeIndex={activeIndex}
              onSelect={onSelectFile}
            />
          </div>
        ) : (
          <span
            className="inline-flex min-w-0 flex-1 items-center gap-2 text-sm font-medium"
            title={activeFilename}
          >
            <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{activeFilename ?? "Document"}</span>
          </span>
        )}

        {parsePreview?.stats && (
          <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">
            {parsePreview.stats.text_count} text ·{" "}
            {parsePreview.stats.table_count} tables ·{" "}
            {parsePreview.stats.picture_count} figures
          </span>
        )}
      </div>

      {showChunks && activeFilename ? (
        <div className="flex min-w-0 items-center border-border p-2 lg:border-l">
          <KnowledgeSearchInput
            value={chunkSearch}
            onSearch={onChunkSearch}
            onClear={onClearChunkSearch}
            hideFilterChip
            hideSubmit
            placeholder="Search chunks…"
            className="max-w-none w-full"
            inputClassName="rounded-full !min-h-9"
          />
        </div>
      ) : (
        <div className="hidden lg:block" />
      )}
    </div>
  );
}

function IngestReviewDocumentColumn({
  failed,
  failureMessage,
  parsePreview,
  highlightItemRefs,
  fallbackPage,
  highlightText,
  chunkLabel,
  hasChunks,
  expanded,
}: {
  failed: boolean;
  failureMessage: string;
  parsePreview: DoclingPreviewResponse | null | undefined;
  highlightItemRefs?: string[];
  fallbackPage?: number | null;
  highlightText?: string;
  chunkLabel?: string;
  hasChunks: boolean;
  expanded: boolean;
}) {
  return (
    <div
      className={cn(
        "flex min-h-[280px] flex-col rounded-lg border border-border/60 bg-muted/30 p-3",
        expanded && "h-full min-h-0",
      )}
    >
      <h3 className="mb-2 shrink-0 text-sm font-semibold">Document</h3>
      <div
        className={cn("min-h-0", expanded ? "flex flex-1 flex-col" : undefined)}
      >
        <DocumentPane
          failed={failed}
          failureMessage={failureMessage}
          parsePreview={parsePreview}
          highlightItemRefs={highlightItemRefs}
          fallbackPage={fallbackPage}
          highlightText={highlightText}
          chunkLabel={chunkLabel}
          hasChunks={hasChunks}
          expanded={expanded}
        />
      </div>
    </div>
  );
}

function IngestReviewAutoOpenFooter({
  autoOpen,
  onAutoOpenChange,
}: {
  autoOpen: IngestPreviewSettings["autoOpen"];
  onAutoOpenChange: (autoOpen: IngestPreviewSettings["autoOpen"]) => void;
}) {
  return (
    <div className="mt-3 flex shrink-0 flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">Auto-open on ingest</span>
      <IngestPreviewAutoOpenControl
        value={autoOpen}
        onChange={onAutoOpenChange}
      />
    </div>
  );
}

function IngestReviewContent({
  taskIds,
  previewFiles,
  demo = false,
  settingsOverride,
  showAutoOpenFooter = false,
  onViewError,
  expanded = false,
}: {
  taskIds: string[];
  previewFiles?: File[];
  demo?: boolean;
  /** When set (e.g. unsaved settings draft), prefer over persisted prefs. */
  settingsOverride?: IngestPreviewSettings;
  /** Auto-open control — onboarding only. */
  showAutoOpenFooter?: boolean;
  onViewError?: (taskId: string) => void;
  expanded?: boolean;
}) {
  const {
    settings,
    updateSettings,
    files,
    activeIndex,
    setSelectedKey,
    activeTaskId,
    failed,
    parsePreview,
    chunkHighlight,
    setChunkHighlight,
    chunkSearch,
    setChunkSearch,
    showChunks,
    highlightItemRefs,
    fallbackPage,
    chunkLabel,
    chunkCount,
    steps,
    failureMessage,
    failedStepIndex,
    activeFilename,
  } = useIngestReviewModel({
    taskIds,
    previewFiles,
    demo,
    settingsOverride,
  });

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      data-testid="ingest-review-content"
    >
      <IngestReviewToolbar
        files={files}
        activeIndex={activeIndex}
        activeFilename={activeFilename}
        parsePreview={parsePreview}
        showChunks={showChunks}
        chunkSearch={chunkSearch}
        onSelectFile={(index) => {
          const file = files[index];
          if (file) setSelectedKey(fileSelectionKey(file));
        }}
        onChunkSearch={setChunkSearch}
        onClearChunkSearch={() => setChunkSearch("")}
      />

      {demo && (
        <p
          className="mt-3 text-xs text-muted-foreground"
          data-testid="ingest-review-demo-banner"
        >
          Sample walkthrough — this document is not uploaded or indexed.
        </p>
      )}

      <div
        className={cn(
          "mt-4 grid min-h-0 gap-4 lg:grid-cols-2",
          expanded ? "flex-1" : "mb-0",
        )}
      >
        <IngestReviewDocumentColumn
          failed={failed}
          failureMessage={failureMessage}
          parsePreview={parsePreview}
          highlightItemRefs={highlightItemRefs}
          fallbackPage={fallbackPage}
          highlightText={chunkHighlight?.text}
          chunkLabel={chunkLabel}
          hasChunks={chunkCount > 0}
          expanded={expanded}
        />
        <IndexPane
          steps={steps}
          filename={activeFilename}
          showIndexingPipeline={settings.showIndexingPipeline}
          showChunkBoundaries={showChunks}
          showChunkContents={settings.showChunkContents}
          failed={failed}
          failedStepIndex={failedStepIndex}
          failureMessage={failureMessage}
          awaitingChunks={chunkCount === 0 && !failed}
          selectedChunkIndex={chunkHighlight?.index ?? null}
          onSelectChunk={(chunk) => {
            setChunkHighlight((prev) =>
              prev?.index === chunk.index ? null : chunk,
            );
          }}
          chunkSearch={chunkSearch}
          onChunkSearchChange={setChunkSearch}
          demoChunks={demo && chunkCount > 0 ? SAMPLE_DEMO_CHUNKS : undefined}
          expanded={expanded}
          onViewError={
            activeTaskId ? () => onViewError?.(activeTaskId) : undefined
          }
        />
      </div>

      {showAutoOpenFooter && (
        <IngestReviewAutoOpenFooter
          autoOpen={settings.autoOpen}
          onAutoOpenChange={(autoOpen) => updateSettings({ autoOpen })}
        />
      )}
    </div>
  );
}

// --- Dialog wrapper ----------------------------------------------------------

export interface IngestReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskIds?: string[];
  previewFiles?: File[];
  /** Client-only walkthrough — no upload or indexing. */
  demo?: boolean;
  /** Prefer these prefs (e.g. unsaved settings draft) over localStorage. */
  settingsOverride?: IngestPreviewSettings;
  /** Show the auto-open preference footer (onboarding only). */
  showAutoOpenFooter?: boolean;
}

export function IngestReviewDialog({
  open,
  onOpenChange,
  taskIds = [],
  previewFiles = [],
  demo = false,
  settingsOverride,
  showAutoOpenFooter = false,
}: IngestReviewDialogProps) {
  const { openTaskDialog } = useTask();
  const [expanded, setExpanded] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);

  // Reset expand state when the dialog re-opens (sync during render).
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setExpanded(false);
    }
  }

  // Skip mounting while closed so preview polls don't run in the background.
  if (!open || (taskIds.length === 0 && previewFiles.length === 0 && !demo)) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex flex-col gap-3 p-4",
          expanded
            ? "h-[95vh] max-w-[95vw] overflow-hidden"
            : "max-h-[90vh] max-w-5xl overflow-y-auto",
        )}
        data-testid="ingest-review-dialog"
      >
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-label={expanded ? "Shrink review" : "Expand review"}
          className="absolute right-11 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          {expanded ? (
            <Minimize2 className="h-4 w-4" />
          ) : (
            <Maximize2 className="h-4 w-4" />
          )}
        </button>
        <DialogHeader className="shrink-0">
          <DialogTitle>
            {demo ? "Ingestion review (sample)" : "Ingestion review"}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {demo
              ? "Sample walkthrough of how a document is parsed and indexed. Nothing is uploaded."
              : "Review how this document is parsed and indexed."}
          </DialogDescription>
        </DialogHeader>
        <IngestReviewContent
          taskIds={taskIds}
          previewFiles={previewFiles}
          demo={demo}
          settingsOverride={settingsOverride}
          showAutoOpenFooter={showAutoOpenFooter}
          expanded={expanded}
          onViewError={(id) => {
            onOpenChange(false);
            openTaskDialog(id);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
