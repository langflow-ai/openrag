"use client";

import {
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  FileIcon,
  Loader2,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";
import {
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import {
  type DoclingPreviewResponse,
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
  markIngestPreviewSeen,
  useIngestPreviewSettings,
} from "@/hooks/use-ingest-preview-settings";
import {
  chunkPageToDoclingRef,
  doclingHasPageImages,
  pageFromDoclingRef,
  summarizeChunkPages,
} from "@/lib/ingest-preview";
import { cn } from "@/lib/utils";

function previewFrameClass(expanded: boolean): string {
  return cn(
    "overflow-auto rounded-md bg-background",
    expanded ? "h-full min-h-0 max-h-none" : "max-h-[420px]",
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
  className,
}: {
  label: string;
  lines: ReadonlyArray<{ id: string; width: string }>;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative rounded-md border border-dashed border-sky-300/80 bg-sky-50/40 p-2 dark:border-sky-500/40 dark:bg-sky-950/20",
        className,
      )}
    >
      <span className="absolute -top-2 left-2 rounded bg-sky-500 px-1.5 py-0.5 text-[10px] font-medium leading-none text-white">
        {label}
      </span>
      <div className="flex flex-1 flex-col gap-1.5 py-1">
        {lines.map((line) => (
          <Skeleton
            key={line.id}
            className={cn(
              "h-2 rounded-full bg-sky-200/70 dark:bg-sky-400/25",
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
        "space-y-3 bg-muted/40 p-3",
        expanded && "min-h-0 flex-1",
      )}
      data-testid="ingest-review-doc-skeleton"
      aria-busy="true"
      aria-label="Loading document layout"
    >
      <div className="rounded-md border-2 border-sky-400 bg-background p-3 shadow-sm">
        <div className="mb-3">
          <SkeletonChunk
            label="Header"
            lines={[
              { id: "h1", width: "w-2/3" },
              { id: "h2", width: "w-1/2" },
            ]}
            className="min-h-12"
          />
        </div>
        <div className="mb-3 grid grid-cols-[1fr_5rem] gap-2">
          <SkeletonChunk
            label="Chunk 1"
            lines={[
              { id: "c1a", width: "w-full" },
              { id: "c1b", width: "w-5/6" },
              { id: "c1c", width: "w-4/5" },
              { id: "c1d", width: "w-3/5" },
            ]}
            className="min-h-20"
          />
          <div className="rounded-md border border-dashed border-sky-300/80 dark:border-sky-500/40" />
        </div>
        <div className="grid grid-cols-[1fr_5rem] gap-2">
          <SkeletonChunk
            label="Chunk 2"
            lines={[
              { id: "c2a", width: "w-full" },
              { id: "c2b", width: "w-5/6" },
              { id: "c2c", width: "w-2/3" },
            ]}
            className="min-h-16"
          />
          <div className="rounded-md border border-dashed border-sky-300/80 dark:border-sky-500/40" />
        </div>
      </div>

      <div className="rounded-md border border-border/60 bg-background p-3 shadow-sm">
        <div className="mb-3 grid grid-cols-2 gap-2">
          <SkeletonChunk
            label="Chunk 3"
            lines={[
              { id: "c3a", width: "w-full" },
              { id: "c3b", width: "w-4/5" },
              { id: "c3c", width: "w-3/5" },
            ]}
            className="min-h-16"
          />
          <SkeletonChunk
            label="Chunk 4"
            lines={[
              { id: "c4a", width: "w-full" },
              { id: "c4b", width: "w-5/6" },
            ]}
            className="min-h-16"
          />
        </div>
        <SkeletonChunk
          label="Chunk 5"
          lines={[
            { id: "c5a", width: "w-full" },
            { id: "c5b", width: "w-5/6" },
            { id: "c5c", width: "w-4/5" },
            { id: "c5d", width: "w-2/3" },
          ]}
          className="min-h-16"
        />
        <p className="mt-3 text-center text-xs text-muted-foreground">2</p>
      </div>
    </div>
  );
}

function DocumentPane({
  failed,
  failureMessage,
  parsePreview,
  previewExpired,
  highlightItems,
  hasChunks,
  expanded = false,
}: {
  failed: boolean;
  failureMessage: string;
  parsePreview: DoclingPreviewResponse | null | undefined;
  previewExpired: boolean;
  highlightItems?: string;
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
            {hasChunks ? " Click a chunk to focus a page." : null}
          </p>
          <DoclingParseViewer
            doclingDocument={doclingDocument}
            highlightItems={highlightItems}
          />
        </div>
      );
    }
    return (
      <div className={cn(frameClass, expanded && "min-h-0 flex-1")}>
        <p className="mb-2 shrink-0 text-xs text-muted-foreground">
          No page image for this format — each region Docling detected is boxed
          and labeled by type.
        </p>
        <DoclingTextPreview doclingDocument={doclingDocument} />
      </div>
    );
  }

  if (previewExpired) {
    return (
      <div
        className="flex h-56 flex-col items-center justify-center gap-2 px-4 text-center text-muted-foreground"
        data-testid="ingest-review-expired"
      >
        <Clock className="h-8 w-8 opacity-60" />
        <p className="text-sm font-medium text-foreground">
          Live preview ended
        </p>
        <p className="text-xs">
          This document is still indexed and searchable.
        </p>
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
  highlightItems,
  pageNumbering,
  onHighlightChunk,
  chunkSearch,
  onChunkSearchChange,
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
  highlightItems?: string;
  pageNumbering: ReturnType<typeof summarizeChunkPages>["numbering"];
  onHighlightChunk: (pageRef: string | undefined) => void;
  chunkSearch: string;
  onChunkSearchChange: (query: string) => void;
  expanded?: boolean;
}) {
  const activeStepIndex = failed ? -1 : steps.findIndex((step) => !step.done);
  const selectedPage = pageFromDoclingRef(highlightItems, pageNumbering);

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

      {showChunkBoundaries && filename && !awaitingChunks && (
        <div className={cn(expanded && "min-h-0 flex-1")}>
          <FileChunksPanel
            filename={filename}
            compact
            fillHeight={expanded}
            showContents={showChunkContents}
            selectedPage={selectedPage}
            hideSearch
            filterQuery={chunkSearch}
            onFilterQueryChange={onChunkSearchChange}
            onChunkSelect={(chunk) => {
              if (chunk.page == null) {
                onHighlightChunk(undefined);
                return;
              }
              const pageRef = chunkPageToDoclingRef(chunk.page, pageNumbering);
              onHighlightChunk(
                highlightItems === pageRef ? undefined : pageRef,
              );
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
          className="h-auto w-auto min-w-[260px] max-w-full justify-between gap-2 px-1.5 py-2 font-medium hover:bg-muted/60"
          data-testid="ingest-review-file-selector"
        >
          <span className="flex min-w-0 items-center gap-2">
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
                    className="gap-2"
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

function IngestReviewContent({
  taskIds,
  previewFiles,
  onViewError,
  expanded = false,
}: {
  taskIds: string[];
  previewFiles?: File[];
  onViewError?: (taskId: string) => void;
  expanded?: boolean;
}) {
  const { settings, updateSettings } = useIngestPreviewSettings();
  const { data: tasks } = useGetTasksQuery({ enabled: taskIds.length > 0 });

  const fromTasks = carouselFilesFromTasks(tasks, taskIds);
  const files: CarouselFile[] =
    fromTasks.length > 0
      ? fromTasks
      : (previewFiles ?? []).map((file) => ({
          taskId: null,
          filePath: null,
          filename: file.name,
        }));

  // Stable across task polls / late-arriving folder batches (not a list index).
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selectedIndex = selectedKey
    ? files.findIndex((f) => fileSelectionKey(f) === selectedKey)
    : -1;
  const activeIndex = selectedIndex >= 0 ? selectedIndex : 0;

  const active = files[activeIndex];
  const activeTaskId = active?.taskId ?? taskIds[0] ?? null;

  const failed = isFileEntryFailed(active?.entry);
  const activeFilePath = active?.filePath ?? null;

  const { data: parsePreview, isLoading: parseLoading } =
    useDoclingPreviewQuery(
      activeTaskId,
      Boolean(activeTaskId) && !failed,
      activeFilePath,
    );
  const { data: indexProof } = useIndexProofQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed,
    activeFilePath,
  );

  const [highlightItems, setHighlightItems] = useState<string | undefined>();
  const [chunkSearch, setChunkSearch] = useState("");
  const activeSelectionKey = active ? fileSelectionKey(active) : "";
  const [prevActiveSelectionKey, setPrevActiveSelectionKey] =
    useState(activeSelectionKey);
  if (activeSelectionKey !== prevActiveSelectionKey) {
    setPrevActiveSelectionKey(activeSelectionKey);
    setHighlightItems(undefined);
    setChunkSearch("");
  }

  const showChunks = settings.showChunkBoundaries;
  const { numbering: pageNumbering } = summarizeChunkPages(
    indexProof?.chunks ?? [],
  );

  const doclingFinished = isPreviewReady(active?.entry);
  const layoutReady = Boolean(parsePreview?.document);
  const previewExpired =
    !failed && !parsePreview?.document && !parseLoading && doclingFinished;
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
      label: "Stored in OpenSearch",
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

  const notifiedRef = useRef<Set<string> | null>(null);
  if (notifiedRef.current === null) {
    notifiedRef.current = new Set();
  }
  const ready = Boolean(indexProof?.ready);
  const activeFilename = active?.filename;
  useEffect(() => {
    if (!settings.completionNotification || !ready || !activeFilename) return;
    const key = activeSelectionKey || activeFilename;
    const notified = notifiedRef.current;
    if (!notified || notified.has(key)) return;
    notified.add(key);
    toast.success("Task completed", {
      description: `${activeFilename} is indexed and searchable.`,
    });
  }, [
    ready,
    settings.completionNotification,
    activeFilename,
    activeSelectionKey,
  ]);

  const canNavigate = files.length > 1;

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      data-testid="ingest-review-content"
    >
      <div className="-mx-4 shrink-0 grid items-center gap-3 border-t border-b border-border px-4 lg:grid-cols-2 lg:gap-0">
        <div className="flex min-w-0 flex-wrap items-center gap-x-8 gap-y-1 lg:pr-4">
          {canNavigate ? (
            <PreviewFileSelector
              files={files}
              activeIndex={activeIndex}
              onSelect={(index) => {
                const file = files[index];
                if (file) setSelectedKey(fileSelectionKey(file));
              }}
            />
          ) : (
            <span
              className="inline-flex min-w-0 items-center gap-2 truncate text-sm font-medium"
              title={active?.filename}
            >
              <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
              {active?.filename ?? "Document"}
            </span>
          )}

          {parsePreview?.stats && (
            <span className="text-xs text-muted-foreground">
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
              onSearch={setChunkSearch}
              onClear={() => setChunkSearch("")}
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

      <div
        className={cn(
          "mt-4 grid min-h-0 gap-4 lg:grid-cols-2",
          expanded ? "flex-1" : "mb-0",
        )}
      >
        <div
          className={cn(
            "flex min-h-[280px] flex-col rounded-lg border border-border/60 bg-muted/30 p-3",
            expanded && "h-full min-h-0",
          )}
        >
          <h3 className="mb-2 shrink-0 text-sm font-semibold">Document</h3>
          <div
            className={cn(
              "min-h-0",
              expanded ? "flex flex-1 flex-col" : undefined,
            )}
          >
            <DocumentPane
              failed={failed}
              failureMessage={failureMessage}
              parsePreview={parsePreview}
              previewExpired={previewExpired}
              highlightItems={highlightItems}
              hasChunks={chunkCount > 0}
              expanded={expanded}
            />
          </div>
        </div>
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
          highlightItems={highlightItems}
          pageNumbering={pageNumbering}
          onHighlightChunk={setHighlightItems}
          chunkSearch={chunkSearch}
          onChunkSearchChange={setChunkSearch}
          expanded={expanded}
          onViewError={
            activeTaskId ? () => onViewError?.(activeTaskId) : undefined
          }
        />
      </div>

      <div className="mt-3 flex shrink-0 flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">
          Auto-open on ingest
        </span>
        <IngestPreviewAutoOpenControl
          value={settings.autoOpen}
          onChange={(autoOpen) => updateSettings({ autoOpen })}
        />
      </div>
    </div>
  );
}

// --- Dialog wrapper ----------------------------------------------------------

export interface IngestReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskIds?: string[];
  filename?: string;
  previewFiles?: File[];
}

export function IngestReviewDialog({
  open,
  onOpenChange,
  taskIds = [],
  previewFiles = [],
}: IngestReviewDialogProps) {
  const { openTaskDialog } = useTask();
  const [expanded, setExpanded] = useState(false);
  const [wasOpen, setWasOpen] = useState(open);

  // Reset expand state + mark seen when the dialog re-opens (sync during render).
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setExpanded(false);
      markIngestPreviewSeen();
    }
  }

  // Skip mounting while closed so preview polls don't run in the background.
  if (!open || (taskIds.length === 0 && previewFiles.length === 0)) {
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
          <DialogTitle>Ingestion review</DialogTitle>
          <DialogDescription className="sr-only">
            Review how this document is parsed and indexed.
          </DialogDescription>
        </DialogHeader>
        <IngestReviewContent
          taskIds={taskIds}
          previewFiles={previewFiles}
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
