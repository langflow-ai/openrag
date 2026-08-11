"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  FileIcon,
  Loader2,
  Maximize2,
  Minimize2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import type { MutableRefObject } from "react";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import {
  type Task,
  type TaskFileEntry,
  useGetTasksQuery,
} from "@/app/api/queries/useGetTasksQuery";
import {
  type DoclingPreviewResponse,
  type DraftChunk,
  type IndexProofChunk,
  ingestPreviewQueryKeys,
  useChunkDraftQuery,
  useCommitChunkDraftMutation,
  useDeleteDraftChunkMutation,
  useDoclingPreviewQuery,
  useIndexProofQuery,
  usePatchDraftChunkMutation,
  useRevertChunkDraftMutation,
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
import { Textarea } from "@/components/ui/textarea";
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

/**
 * Live index-proof returns chunks + embeddings + ready together. Reveal the
 * last three pipeline steps ~700ms apart so they don't all check off at once.
 * Returns how many of those steps to show as done (0–3).
 */
function useStaggeredPostLayoutReveal(
  enabled: boolean,
  resetKey: string,
): number {
  const [revealed, setRevealed] = useState(0);
  const [prevResetKey, setPrevResetKey] = useState(resetKey);
  const [prevEnabled, setPrevEnabled] = useState(enabled);

  // Reset inline when the file or stagger gate flips — avoid a stale paint.
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  if (resetKey !== prevResetKey) {
    setPrevResetKey(resetKey);
    setRevealed(0);
  }
  if (enabled !== prevEnabled) {
    setPrevEnabled(enabled);
    setRevealed(0);
  }

  useEffect(() => {
    if (!enabled) return;
    // First step stays "active" briefly, then each completes in sequence.
    const delays = [700, 1400, 2100];
    const timers = delays.map((ms, index) =>
      setTimeout(() => setRevealed(index + 1), ms),
    );
    return () => {
      for (const timer of timers) clearTimeout(timer);
    };
  }, [enabled, resetKey]);

  return revealed;
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
  waitingForDocument = true,
  onRetryPreview,
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
  /** Still polling Docling cache (404/null). False once exhausted or errored. */
  waitingForDocument?: boolean;
  onRetryPreview?: () => void;
}) {
  const doclingDocument = parsePreview?.document;
  const frameClass = previewFrameClass(expanded);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

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
        <div
          ref={scrollContainerRef}
          className={cn(frameClass, expanded && "min-h-0 flex-1")}
        >
          <p className="mb-2 shrink-0 text-xs text-muted-foreground">
            Blue boxes mark parsed text, tables, and figures.
            {hasChunks ? " Click a chunk to focus its region." : null}
          </p>
          <DoclingParseViewer
            doclingDocument={doclingDocument}
            highlightItemRefs={highlightItemRefs}
            fallbackPage={fallbackPage}
            chunkLabel={chunkLabel}
            scrollContainerRef={scrollContainerRef}
          />
        </div>
      );
    }
    return (
      <div
        ref={scrollContainerRef}
        className={cn(frameClass, expanded && "min-h-0 flex-1")}
      >
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

  if (waitingForDocument) {
    return <DoclingDocSkeleton expanded={expanded} />;
  }

  return (
    <div
      className="flex h-56 flex-col items-center justify-center gap-3 px-4 text-center text-muted-foreground"
      data-testid="ingest-review-doc-unavailable"
    >
      <p className="text-md font-medium text-foreground">
        Document preview unavailable
      </p>
      <p className="text-xs">
        Ingest may have finished, but the parse preview never arrived. You can
        retry or close this dialog — the file is still searchable if indexing
        completed.
      </p>
      {onRetryPreview ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onRetryPreview}
          data-testid="ingest-review-doc-retry"
        >
          Retry preview
        </Button>
      ) : null}
    </div>
  );
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
  // Number in source order before filtering so search does not renumber Chunk N.
  const numbered = chunks.map((chunk, index) => ({
    ...chunk,
    displayIndex: index + 1,
  }));
  const needle = chunkSearch.trim().toLowerCase();
  const visible = needle
    ? numbered.filter((chunk) =>
        chunk.text_preview.toLowerCase().includes(needle),
      )
    : numbered;

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
      {visible.map((chunk) => {
        const chunkIndex = chunk.displayIndex;
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
              <blockquote className="min-w-0 text-xs text-muted-foreground leading-relaxed break-words [overflow-wrap:anywhere] whitespace-pre-wrap">
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

function DraftChunksList({
  chunks,
  showContents,
  chunkSearch,
  selectedChunkIndex,
  onSelectChunk,
  pendingTexts,
  onPendingTextChange,
  onDeleteChunk,
  deletingChunkId,
  chunksTruncated = false,
  totalChunksInIndex,
  expanded = false,
}: {
  chunks: DraftChunk[];
  showContents: boolean;
  chunkSearch: string;
  selectedChunkIndex?: number | null;
  onSelectChunk: (chunk: {
    index: number;
    page: number | null;
    text: string;
  }) => void;
  pendingTexts: Record<string, string>;
  onPendingTextChange: (chunkId: string, text: string | null) => void;
  onDeleteChunk: (chunkId: string) => Promise<void> | void;
  deletingChunkId?: string | null;
  chunksTruncated?: boolean;
  totalChunksInIndex?: number | null;
  expanded?: boolean;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);

  const displayText = (chunk: DraftChunk) =>
    pendingTexts[chunk.chunk_id] ?? chunk.text;

  const numbered = chunks.map((chunk, index) => ({
    ...chunk,
    displayIndex: index + 1,
  }));
  const needle = chunkSearch.trim().toLowerCase();
  const visible = needle
    ? numbered.filter((chunk) =>
        displayText(chunk).toLowerCase().includes(needle),
      )
    : numbered;

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
      data-testid="ingest-review-draft-chunks"
    >
      {chunksTruncated ? (
        <p
          className="text-xs text-amber-700 dark:text-amber-400"
          data-testid="ingest-review-chunks-truncated"
        >
          Showing {chunks.length}
          {totalChunksInIndex != null ? ` of ${totalChunksInIndex}` : ""}{" "}
          indexed chunks — edits apply only to the loaded set.
        </p>
      ) : null}
      {visible.map((chunk) => {
        const chunkIndex = chunk.displayIndex;
        const selected = selectedChunkIndex === chunkIndex;
        const editing = editingId === chunk.chunk_id;
        const deleting = deletingChunkId === chunk.chunk_id;
        const text = displayText(chunk);
        const edited =
          chunk.dirty ||
          (pendingTexts[chunk.chunk_id] !== undefined &&
            pendingTexts[chunk.chunk_id] !== chunk.text);

        return (
          <div
            key={chunk.chunk_id}
            className={cn(
              "w-full rounded-lg border border-border/50 bg-muted p-2.5 text-left",
              selected && "border-primary/60 ring-1 ring-primary/30",
            )}
          >
            <div className="mb-2 flex min-w-0 items-center justify-between gap-2">
              <button
                type="button"
                className="flex min-w-0 flex-wrap items-center gap-2 text-left"
                onClick={() =>
                  onSelectChunk({
                    index: chunkIndex,
                    page: chunk.page ?? null,
                    text,
                  })
                }
              >
                <span className="text-xs font-bold">Chunk {chunkIndex}</span>
                <Badge variant="secondary" className="text-xxs">
                  {text.length} chars
                </Badge>
                {edited ? (
                  <Badge variant="outline" className="text-xxs">
                    edited
                  </Badge>
                ) : null}
              </button>
              <div className="flex shrink-0 items-center gap-1">
                {editing ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    aria-label="Done editing"
                    onClick={() => setEditingId(null)}
                  >
                    Done
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0"
                    aria-label="Edit chunk"
                    disabled={deleting}
                    onClick={() => {
                      setEditingId(chunk.chunk_id);
                      if (pendingTexts[chunk.chunk_id] === undefined) {
                        onPendingTextChange(chunk.chunk_id, chunk.text);
                      }
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  aria-label="Delete chunk"
                  disabled={deleting || chunks.length <= 1}
                  onClick={() => void onDeleteChunk(chunk.chunk_id)}
                >
                  {deleting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
            </div>
            {editing ? (
              <Textarea
                autoFocus
                value={text}
                onChange={(e) =>
                  onPendingTextChange(chunk.chunk_id, e.target.value)
                }
                className="min-h-24 text-xs"
                data-testid="ingest-review-chunk-editor"
              />
            ) : showContents ? (
              <blockquote className="min-w-0 text-xs text-muted-foreground leading-relaxed break-words [overflow-wrap:anywhere] whitespace-pre-wrap">
                {text}
              </blockquote>
            ) : (
              <p className="text-xs text-muted-foreground">
                {chunk.page != null ? `page ${chunk.page}` : "chunk"} ·{" "}
                {text.length} chars
              </p>
            )}
          </div>
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
  draftChunks,
  pendingTexts,
  onPendingTextChange,
  onDeleteDraftChunk,
  deletingChunkId,
  chunksTruncated = false,
  totalChunksInIndex,
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
  draftChunks?: DraftChunk[];
  pendingTexts?: Record<string, string>;
  onPendingTextChange?: (chunkId: string, text: string | null) => void;
  onDeleteDraftChunk?: (chunkId: string) => Promise<void> | void;
  deletingChunkId?: string | null;
  chunksTruncated?: boolean;
  totalChunksInIndex?: number | null;
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

      {showChunkBoundaries &&
        filename &&
        !awaitingChunks &&
        !demoChunks &&
        draftChunks &&
        pendingTexts &&
        onPendingTextChange &&
        onDeleteDraftChunk && (
          <div className={cn(expanded && "min-h-0 flex-1")}>
            <DraftChunksList
              chunks={draftChunks}
              showContents={showChunkContents}
              chunkSearch={chunkSearch}
              selectedChunkIndex={selectedChunkIndex}
              onSelectChunk={onSelectChunk}
              pendingTexts={pendingTexts}
              onPendingTextChange={onPendingTextChange}
              onDeleteChunk={onDeleteDraftChunk}
              deletingChunkId={deletingChunkId}
              chunksTruncated={chunksTruncated}
              totalChunksInIndex={totalChunksInIndex}
              expanded={expanded}
            />
          </div>
        )}

      {showChunkBoundaries &&
        filename &&
        !awaitingChunks &&
        !demoChunks &&
        !draftChunks && (
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
  const queryClient = useQueryClient();
  const previewReady = !demo && isPreviewReady(active?.entry);

  const {
    data: liveParsePreview,
    isFetching: parsePreviewFetching,
    isPending: parsePreviewPending,
    isError: parsePreviewError,
    refetch: refetchParsePreview,
  } = useDoclingPreviewQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed,
    activeFilePath,
  );
  const { data: liveIndexProof } = useIndexProofQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed,
    activeFilePath,
  );
  const indexProofReady = Boolean(liveIndexProof?.ready);
  const { data: liveChunkDraft } = useChunkDraftQuery(
    activeTaskId,
    Boolean(activeTaskId) && !failed && indexProofReady,
    activeFilePath,
  );
  const patchDraftChunk = usePatchDraftChunkMutation(
    activeTaskId,
    activeFilePath,
  );
  const deleteDraftChunk = useDeleteDraftChunkMutation(
    activeTaskId,
    activeFilePath,
  );
  const revertChunkDraft = useRevertChunkDraftMutation(
    activeTaskId,
    activeFilePath,
  );
  const commitChunkDraft = useCommitChunkDraftMutation(
    activeTaskId,
    activeFilePath,
  );

  // No Docling interval poll. useQuery fetches on mount / query-key change;
  // invalidate only when phase or preview-ready *transitions* while we still
  // lack a document (avoids a mount double-fetch and effect cascades).
  const filePhase = active?.entry?.phase;
  const phaseReadyKey = `${activeTaskId ?? ""}:${activeFilePath ?? ""}:${filePhase ?? ""}:${previewReady}`;
  const prevPhaseReadyKeyRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevPhaseReadyKeyRef.current;
    prevPhaseReadyKeyRef.current = phaseReadyKey;
    if (prev === null || prev === phaseReadyKey) return;
    if (!activeTaskId || failed || liveParsePreview?.document) return;
    void queryClient.invalidateQueries({
      queryKey: ingestPreviewQueryKeys.docling(activeTaskId, activeFilePath),
    });
  }, [
    phaseReadyKey,
    activeTaskId,
    activeFilePath,
    failed,
    liveParsePreview?.document,
    queryClient,
  ]);

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
  // Prefer the page from text→item match (indexed chunk.page is often wrong).
  // Fall back to the chunk's page so PDF overlays still have a scroll target.
  const fallbackPage =
    doclingMatch?.page ??
    (chunkHighlight?.page != null
      ? pageNumbering === "zero-based"
        ? chunkHighlight.page + 1
        : chunkHighlight.page
      : null);
  const chunkLabel =
    chunkHighlight != null ? `Chunk ${chunkHighlight.index}` : undefined;

  const doclingFinished = demo ? demoPhase >= 1 : previewReady;
  const layoutReady = Boolean(parsePreview?.document);
  // Skeleton while ingest is still parsing, or while a fetch/retry is in flight.
  // Once preview-ready and settled with no document → unavailable + retry.
  const waitingForDocument = demo
    ? demoPhase < 1
    : Boolean(activeTaskId) &&
      !failed &&
      !parsePreview?.document &&
      (!previewReady ||
        parsePreviewPending ||
        parsePreviewFetching ||
        (liveParsePreview === undefined && !parsePreviewError));
  const retryParsePreview = () => {
    if (!activeTaskId) return;
    void queryClient.invalidateQueries({
      queryKey: ingestPreviewQueryKeys.docling(activeTaskId, activeFilePath),
    });
    void refetchParsePreview();
  };
  const chunkCount = indexProof?.chunk_count ?? 0;
  const embeddingsReady = Boolean(indexProof?.embedding_dimensions);
  const storedReady = Boolean(indexProof?.ready);
  // Index-proof is atomic after COMPLETE — stagger only the live UI reveal.
  const proofComplete = chunkCount > 0 && embeddingsReady && storedReady;
  const staggerReveal = useStaggeredPostLayoutReveal(
    !demo && !failed && proofComplete,
    activeSelectionKey,
  );
  const chunksDone =
    chunkCount > 0 && (demo || failed || !proofComplete || staggerReveal >= 1);
  const embeddingsDone =
    embeddingsReady && (demo || failed || !proofComplete || staggerReveal >= 2);
  const storedDone =
    storedReady && (demo || failed || !proofComplete || staggerReveal >= 3);
  const steps: PipelineStep[] = [
    {
      id: "layout",
      done: layoutReady || doclingFinished,
      label: "Reading layout",
    },
    { id: "chunks", done: chunksDone, label: "Creating chunks" },
    {
      id: "embeddings",
      done: embeddingsDone,
      label: "Generating embeddings",
    },
    {
      id: "stored",
      done: storedDone,
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

  const draftChunks = demo ? undefined : liveChunkDraft?.chunks;
  const draftDirty = Boolean(liveChunkDraft?.dirty);
  const chunksTruncated = Boolean(liveChunkDraft?.chunks_truncated);
  const totalChunksInIndex = liveChunkDraft?.total_chunks_in_index ?? null;

  const saveDraftText = async (chunkId: string, text: string) => {
    try {
      await patchDraftChunk.mutateAsync({ chunkId, text });
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to update chunk",
      );
      throw error;
    }
  };

  const deleteDraftChunkHandler = async (chunkId: string) => {
    try {
      await deleteDraftChunk.mutateAsync({ chunkId });
      toast.success("Chunk removed from draft");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to delete chunk",
      );
      throw error;
    }
  };

  const revertDraft = async () => {
    try {
      await revertChunkDraft.mutateAsync();
      toast.success("Reverted to Docling original");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to revert chunks",
      );
      throw error;
    }
  };

  const commitDraft = async () => {
    try {
      const result = await commitChunkDraft.mutateAsync();
      if (result.committed === false) {
        return result;
      }
      const docLabel =
        result.filename || activeFilename || result.document_id || "document";
      const modified = result.modified_chunk_ids ?? [];
      const removed = result.removed_chunk_ids ?? [];
      const idParts: string[] = [];
      if (modified.length > 0) {
        idParts.push(
          modified.length === 1
            ? `chunk ${modified[0]}`
            : `chunks ${modified.join(", ")}`,
        );
      }
      if (removed.length > 0) {
        idParts.push(
          removed.length === 1
            ? `removed ${removed[0]}`
            : `removed ${removed.join(", ")}`,
        );
      }
      const detail =
        idParts.length > 0
          ? `${idParts.join("; ")} in ${docLabel}`
          : `chunks in ${docLabel}`;
      toast.success("Chunks successfully modified", {
        description: detail,
      });
      return result;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to save chunks",
      );
      throw error;
    }
  };

  return {
    settings,
    updateSettings,
    files,
    activeIndex,
    setSelectedKey,
    activeTaskId,
    failed,
    parsePreview,
    waitingForDocument,
    retryParsePreview,
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
    draftChunks,
    draftDirty,
    chunksTruncated,
    totalChunksInIndex,
    saveDraftText,
    deleteDraftChunkHandler,
    revertDraft,
    commitDraft,
    deletingChunkId: deleteDraftChunk.isPending
      ? (deleteDraftChunk.variables?.chunkId ?? null)
      : null,
    committing: commitChunkDraft.isPending,
    reverting: revertChunkDraft.isPending,
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
  waitingForDocument,
  onRetryPreview,
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
  waitingForDocument: boolean;
  onRetryPreview: () => void;
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
          waitingForDocument={waitingForDocument}
          onRetryPreview={onRetryPreview}
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

type LeaveAction =
  | { type: "close" }
  | { type: "switchFile"; key: string }
  | { type: "viewError"; taskId: string };

type ChunkDraftLeaveGuard = {
  hasUnsavedChanges: () => boolean;
  requestLeaveConfirm: (action?: LeaveAction) => void;
};

function useChunkDraftSessionUi({
  selectionKey,
  files,
  draftChunks,
  draftDirty,
  saveDraftText,
  deleteDraftChunkHandler,
  revertDraft,
  commitDraft,
  setSelectedKey,
  leaveGuardRef,
  onClose,
  onOpenTaskDialog,
}: {
  selectionKey: string;
  files: CarouselFile[];
  draftChunks: DraftChunk[] | undefined;
  draftDirty: boolean;
  saveDraftText: (chunkId: string, text: string) => Promise<unknown>;
  deleteDraftChunkHandler: (chunkId: string) => Promise<void>;
  revertDraft: () => Promise<unknown>;
  commitDraft: () => Promise<unknown>;
  setSelectedKey: (key: string) => void;
  leaveGuardRef?: MutableRefObject<ChunkDraftLeaveGuard | null>;
  onClose?: () => void;
  onOpenTaskDialog?: (taskId: string) => void;
}) {
  const [pendingTexts, setPendingTexts] = useState<Record<string, string>>({});
  const [flushing, setFlushing] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [leaveIntent, setLeaveIntent] = useState(false);
  const [draftUiKey, setDraftUiKey] = useState(selectionKey);
  const footerRef = useRef<HTMLDivElement | null>(null);
  const pendingActionRef = useRef<LeaveAction | null>(null);

  // Reset local draft UI when the selected file changes (render-time adjust).
  if (selectionKey !== draftUiKey) {
    setDraftUiKey(selectionKey);
    setPendingTexts({});
    setConfirmOpen(false);
    setLeaveIntent(false);
    pendingActionRef.current = null;
  }

  const hasEmptyPendingText = Boolean(
    draftChunks?.some((chunk) => {
      const pending = pendingTexts[chunk.chunk_id];
      return pending !== undefined && !pending.trim();
    }),
  );
  const hasPendingTextChanges = Boolean(
    draftChunks?.some((chunk) => {
      const pending = pendingTexts[chunk.chunk_id];
      return pending !== undefined && pending !== chunk.text;
    }),
  );
  const hasUnsavedChanges = hasPendingTextChanges || draftDirty;
  const canSave = hasUnsavedChanges && !hasEmptyPendingText;
  const canConfirm = canSave;
  const confirmBlockedReason = hasEmptyPendingText
    ? "Chunk text cannot be empty."
    : null;
  const showSaveFooter = Boolean(draftChunks && draftChunks.length > 0);

  const hasUnsavedChangesRef = useRef(hasUnsavedChanges);
  hasUnsavedChangesRef.current = hasUnsavedChanges;

  // Stable: only refs + setState — safe to publish once on the leave guard.
  const requestLeaveConfirm = useCallback(
    (action: LeaveAction = { type: "close" }) => {
      pendingActionRef.current = action;
      setLeaveIntent(true);
      setConfirmOpen(true);
      requestAnimationFrame(() => {
        footerRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
        });
      });
    },
    [],
  );

  useEffect(() => {
    if (!leaveGuardRef) return;
    leaveGuardRef.current = {
      hasUnsavedChanges: () => hasUnsavedChangesRef.current,
      requestLeaveConfirm,
    };
    return () => {
      leaveGuardRef.current = null;
    };
  }, [leaveGuardRef, requestLeaveConfirm]);

  const handlePendingTextChange = (chunkId: string, text: string | null) => {
    setPendingTexts((prev) => {
      if (text === null) {
        const next = { ...prev };
        delete next[chunkId];
        return next;
      }
      return { ...prev, [chunkId]: text };
    });
  };

  const handleDeleteDraftChunk = async (chunkId: string) => {
    await deleteDraftChunkHandler(chunkId);
    handlePendingTextChange(chunkId, null);
  };

  const handleConfirmOpenChange = (open: boolean) => {
    setConfirmOpen(open);
    if (!open) {
      setLeaveIntent(false);
      pendingActionRef.current = null;
    }
  };

  const finishLeaveAction = () => {
    const action = pendingActionRef.current;
    pendingActionRef.current = null;
    setLeaveIntent(false);
    if (!action || action.type === "close") {
      onClose?.();
      return;
    }
    if (action.type === "switchFile") {
      setSelectedKey(action.key);
      return;
    }
    onClose?.();
    onOpenTaskDialog?.(action.taskId);
  };

  const handleCommit = async () => {
    if (hasEmptyPendingText) {
      toast.error("Chunk text cannot be empty");
      throw new Error("Chunk text cannot be empty");
    }
    setFlushing(true);
    try {
      const pendingUpdates = (draftChunks ?? []).flatMap((chunk) => {
        const pending = pendingTexts[chunk.chunk_id];
        if (pending === undefined || pending === chunk.text) return [];
        if (!pending.trim()) {
          toast.error("Chunk text cannot be empty");
          throw new Error("Chunk text cannot be empty");
        }
        // Preserve intentional whitespace; backend requires non-empty strip.
        return [{ chunkId: chunk.chunk_id, text: pending }];
      });
      await Promise.all(
        pendingUpdates.map(({ chunkId, text }) => saveDraftText(chunkId, text)),
      );
      await commitDraft();
      // Clear local pending only after commit succeeds so a failed commit
      // still leaves the user's working copy in the editor.
      setPendingTexts({});
      // Saving always keeps the review dialog open — leave/switch/view-error
      // only proceeds after Revert (or a later close with no unsaved edits).
      pendingActionRef.current = null;
      setLeaveIntent(false);
    } finally {
      setFlushing(false);
    }
  };

  const handleRevert = async () => {
    await revertDraft();
    setPendingTexts({});
    if (leaveIntent) {
      finishLeaveAction();
    }
  };

  const handleSelectFile = (index: number) => {
    const file = files[index];
    if (!file) return;
    const nextKey = fileSelectionKey(file);
    if (nextKey === selectionKey) return;
    if (hasUnsavedChanges) {
      requestLeaveConfirm({ type: "switchFile", key: nextKey });
      return;
    }
    setSelectedKey(nextKey);
  };

  return {
    pendingTexts,
    flushing,
    confirmOpen,
    leaveIntent,
    footerRef,
    canSave,
    canConfirm,
    confirmBlockedReason,
    showSaveFooter,
    handlePendingTextChange,
    handleDeleteDraftChunk,
    handleConfirmOpenChange,
    handleCommit,
    handleRevert,
    handleSelectFile,
  };
}

function ChunkDraftSaveFooter({
  visible,
  canSave,
  canConfirm,
  confirmBlockedReason,
  confirmOpen,
  onConfirmOpenChange,
  leaveIntent = false,
  committing,
  reverting,
  flushing,
  onCommit,
  onRevert,
}: {
  visible: boolean;
  canSave: boolean;
  canConfirm: boolean;
  confirmBlockedReason?: string | null;
  confirmOpen: boolean;
  onConfirmOpenChange: (open: boolean) => void;
  leaveIntent?: boolean;
  committing: boolean;
  reverting: boolean;
  flushing?: boolean;
  onCommit: () => Promise<void>;
  onRevert: () => Promise<void>;
}) {
  if (!visible) return null;

  const busy = committing || reverting || Boolean(flushing);

  return (
    <div
      className="mt-4 shrink-0 border-t border-border/60 pt-3"
      data-testid="ingest-review-chunk-save-footer"
    >
      {confirmOpen ? (
        <div
          className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
          data-testid="ingest-review-save-confirm-panel"
        >
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-medium">
              {leaveIntent ? "Unsaved chunk changes" : "Save chunk changes?"}
            </p>
            <p className="text-xs text-muted-foreground">
              {leaveIntent
                ? "Confirm saves and keeps this review open. Revert discards edits and continues leaving."
                : "Confirm updates search and chat. Revert restores the Docling original for this preview."}
            </p>
            {confirmBlockedReason ? (
              <p className="text-xs text-destructive">{confirmBlockedReason}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              data-testid="ingest-review-save-cancel"
              onClick={() => onConfirmOpenChange(false)}
            >
              {leaveIntent ? "Keep editing" : "Cancel"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={busy}
              data-testid="ingest-review-save-revert"
              onClick={() => {
                void (async () => {
                  try {
                    await onRevert();
                    onConfirmOpenChange(false);
                  } catch {
                    /* toast handled by caller */
                  }
                })();
              }}
            >
              {reverting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                "Revert"
              )}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={busy || !canConfirm}
              data-testid="ingest-review-save-confirm"
              onClick={() => {
                void (async () => {
                  try {
                    await onCommit();
                    onConfirmOpenChange(false);
                  } catch {
                    /* toast handled by caller */
                  }
                })();
              }}
            >
              {committing || flushing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                "Confirm"
              )}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            {canSave
              ? "Unsaved chunk changes — search still uses the last saved version."
              : "Edit or delete chunks, then save to update search and chat."}
          </p>
          <Button
            type="button"
            size="sm"
            disabled={!canSave || busy}
            data-testid="ingest-review-save-chunks"
            onClick={() => onConfirmOpenChange(true)}
          >
            Save
          </Button>
        </div>
      )}
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
  onOpenTaskDialog,
  expanded = false,
  leaveGuardRef,
  onClose,
}: {
  taskIds: string[];
  previewFiles?: File[];
  demo?: boolean;
  /** When set (e.g. unsaved settings draft), prefer over persisted prefs. */
  settingsOverride?: IngestPreviewSettings;
  /** Auto-open control — onboarding only. */
  showAutoOpenFooter?: boolean;
  onViewError?: (taskId: string) => void;
  /** Called after leave Confirm/Revert when navigating to task error. */
  onOpenTaskDialog?: (taskId: string) => void;
  expanded?: boolean;
  leaveGuardRef?: MutableRefObject<ChunkDraftLeaveGuard | null>;
  onClose?: () => void;
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
    waitingForDocument,
    retryParsePreview,
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
    draftChunks,
    draftDirty,
    chunksTruncated,
    totalChunksInIndex,
    saveDraftText,
    deleteDraftChunkHandler,
    revertDraft,
    commitDraft,
    deletingChunkId,
    committing,
    reverting,
  } = useIngestReviewModel({
    taskIds,
    previewFiles,
    demo,
    settingsOverride,
  });

  const activeFile = files[activeIndex];
  const selectionKey = activeFile ? fileSelectionKey(activeFile) : "";
  const {
    pendingTexts,
    flushing,
    confirmOpen,
    leaveIntent,
    footerRef,
    canSave,
    canConfirm,
    confirmBlockedReason,
    showSaveFooter,
    handlePendingTextChange,
    handleDeleteDraftChunk,
    handleConfirmOpenChange,
    handleCommit,
    handleRevert,
    handleSelectFile,
  } = useChunkDraftSessionUi({
    selectionKey,
    files,
    draftChunks,
    draftDirty,
    saveDraftText,
    deleteDraftChunkHandler,
    revertDraft,
    commitDraft,
    setSelectedKey,
    leaveGuardRef,
    onClose,
    onOpenTaskDialog,
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
        onSelectFile={handleSelectFile}
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
          waitingForDocument={waitingForDocument}
          onRetryPreview={retryParsePreview}
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
          draftChunks={draftChunks}
          pendingTexts={pendingTexts}
          onPendingTextChange={handlePendingTextChange}
          onDeleteDraftChunk={handleDeleteDraftChunk}
          deletingChunkId={deletingChunkId}
          chunksTruncated={chunksTruncated}
          totalChunksInIndex={totalChunksInIndex}
          expanded={expanded}
          onViewError={
            activeTaskId ? () => onViewError?.(activeTaskId) : undefined
          }
        />
      </div>

      <div ref={footerRef}>
        <ChunkDraftSaveFooter
          visible={showSaveFooter}
          canSave={canSave}
          canConfirm={canConfirm}
          confirmBlockedReason={confirmBlockedReason}
          confirmOpen={confirmOpen}
          onConfirmOpenChange={handleConfirmOpenChange}
          leaveIntent={leaveIntent}
          committing={committing}
          reverting={reverting}
          flushing={flushing}
          onCommit={handleCommit}
          onRevert={handleRevert}
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

export type { ChunkDraftLeaveGuard };

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
  const leaveGuardRef = useRef<ChunkDraftLeaveGuard | null>(null);

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

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && leaveGuardRef.current?.hasUnsavedChanges()) {
      leaveGuardRef.current.requestLeaveConfirm();
      return;
    }
    onOpenChange(nextOpen);
  };

  const closeDialog = () => onOpenChange(false);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
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
          leaveGuardRef={leaveGuardRef}
          onClose={closeDialog}
          onOpenTaskDialog={openTaskDialog}
          onViewError={(id) => {
            if (leaveGuardRef.current?.hasUnsavedChanges()) {
              leaveGuardRef.current.requestLeaveConfirm({
                type: "viewError",
                taskId: id,
              });
              return;
            }
            onOpenChange(false);
            openTaskDialog(id);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
