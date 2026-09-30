"use client";

import { Check, Copy, Loader2 } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useFileScopedChunksQuery } from "@/app/api/queries/useFileScopedChunksQuery";
import {
  type ChunkResult,
  RELEVANCE_HIGH_THRESHOLD,
  RELEVANCE_MED_THRESHOLD,
  type RelevanceTier,
} from "@/app/api/queries/useGetSearchQuery";
import { HighlightedText } from "@/components/highlighted-text";
import { KnowledgeSearchInput } from "@/components/knowledge-search-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { trackButton } from "@/lib/analytics";
import { cn } from "@/lib/utils";

/** Document order for stable Chunk N labels (search hit order is not page order). */
function compareChunksByDocumentOrder(a: ChunkResult, b: ChunkResult): number {
  const pageA = typeof a.page === "number" ? a.page : Number.POSITIVE_INFINITY;
  const pageB = typeof b.page === "number" ? b.page : Number.POSITIVE_INFINITY;
  if (pageA !== pageB) return pageA - pageB;
  return (a.chunk_id ?? a.id ?? "").localeCompare(b.chunk_id ?? b.id ?? "");
}

export interface FileChunksPanelProps {
  filename: string;
  /** Compact layout for dialogs (e.g. ingest review). */
  compact?: boolean;
  /** When false, show metadata only (no chunk body). Default true. */
  showContents?: boolean;
  selectedPage?: number | null;
  /** Prefer exact chunk selection over page-wide selection. */
  selectedChunkIndex?: number | null;
  onChunkSelect?: (chunk: ChunkResult) => void;
  className?: string;
  /** Hide built-in search (parent renders it elsewhere, e.g. above pipeline steps). */
  hideSearch?: boolean;
  /** Controlled filter query — use with hideSearch when search lives outside the panel. */
  filterQuery?: string;
  onFilterQueryChange?: (query: string) => void;
  /** Grow to fill parent height (ingest-review expand); replaces compact max-height. */
  fillHeight?: boolean;
  /** Original search query from the knowledge page — used to fetch highlighted chunks. */
  searchQuery?: string;
}

function chunkMatches(chunk: ChunkResult, needle: string): boolean {
  const text = chunk.text.toLowerCase();
  const indexStr = chunk.index != null ? String(chunk.index) : "";
  // Full phrase first; fall back to any token for multi-word queries.
  if (text.includes(needle) || indexStr.includes(needle)) return true;
  const tokens = needle.split(/\s+/).filter((t) => t.length > 0);
  return tokens.length > 1 && tokens.some((t) => text.includes(t));
}

const SCORE_TIER_CLASS: Record<RelevanceTier, string> = {
  high: "border-emerald-500 text-emerald-700 bg-emerald-50 dark:border-emerald-400 dark:text-emerald-300 dark:bg-emerald-950/40",
  medium:
    "border-amber-500 text-amber-700 bg-amber-50 dark:border-amber-400 dark:text-amber-300 dark:bg-amber-950/40",
  low: "border-slate-400 text-slate-600 bg-slate-50 dark:border-slate-500 dark:text-slate-400 dark:bg-slate-900/40",
};

function FileChunkCard({
  chunk,
  listIndex,
  compact,
  showContents,
  selected,
  interactive,
  copied,
  scoreTier,
  scoreLabel,
  onCopy,
  onSelect,
}: {
  chunk: ChunkResult;
  listIndex: number;
  compact: boolean;
  showContents: boolean;
  selected: boolean;
  interactive: boolean;
  copied: boolean;
  scoreTier?: RelevanceTier;
  scoreLabel?: string;
  onCopy: (text: string, listIndex: number) => void;
  onSelect?: () => void;
}) {
  const cardClass = cn(
    "min-w-0 rounded-lg border border-border/50 bg-muted p-3 text-left",
    compact && "p-2.5",
    interactive && "w-full transition-colors hover:border-primary/40",
    selected && "border-primary/60 ring-1 ring-primary/30",
  );

  const body = (
    <>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className={cn(
              "font-bold text-foreground",
              compact ? "text-xs" : "text-sm",
            )}
          >
            Chunk {chunk.index}
          </span>
          <Badge
            variant="secondary"
            className="text-xxs bg-background text-foreground border border-border"
          >
            {chunk.text.length} chars
          </Badge>
          {!compact && (
            <Button
              onClick={(e) => {
                e.stopPropagation();
                onCopy(chunk.text, listIndex);
              }}
              variant="ghost"
              size="sm"
              type="button"
              aria-label={copied ? "Chunk copied" : "Copy chunk text"}
            >
              {copied ? (
                <Check className="text-muted-foreground" />
              ) : (
                <Copy className="text-muted-foreground" />
              )}
            </Button>
          )}
        </div>
        {scoreLabel && (
          <Badge
            variant="secondary"
            className={cn(
              "shrink-0 text-xxs border",
              scoreTier
                ? SCORE_TIER_CLASS[scoreTier]
                : "bg-background text-foreground border-border",
            )}
          >
            {scoreLabel}
          </Badge>
        )}
      </div>
      {showContents ? (
        <blockquote
          className={cn(
            "min-w-0 text-foreground leading-relaxed break-words [overflow-wrap:anywhere] whitespace-pre-wrap",
            compact ? "text-xs" : "text-sm ml-1.5",
          )}
        >
          <HighlightedText
            highlights={chunk.highlights ?? []}
            fallbackText={chunk.text}
          />
        </blockquote>
      ) : (
        <p className="text-xs text-muted-foreground">
          {chunk.page != null ? `page ${chunk.page}` : "chunk"} ·{" "}
          {chunk.text.length} chars
        </p>
      )}
    </>
  );

  if (interactive) {
    return (
      <button type="button" className={cardClass} onClick={onSelect}>
        {body}
      </button>
    );
  }

  return <div className={cardClass}>{body}</div>;
}

/**
 * Searchable per-file chunk list shared by `/knowledge/chunks` and ingest review.
 * Loads this file’s chunks once, then filters locally so paste-from-chunk works.
 */
export function FileChunksPanel({
  filename,
  compact = false,
  showContents = true,
  selectedPage,
  selectedChunkIndex,
  onChunkSelect,
  className,
  hideSearch = false,
  filterQuery,
  onFilterQueryChange,
  fillHeight = false,
  searchQuery,
}: FileChunksPanelProps) {
  const { file, isFetching, isSearchFetching } = useFileScopedChunksQuery(
    filename,
    searchQuery,
  );
  const allChunks = useMemo(() => {
    const sorted = [...(file?.chunks ?? [])].sort(compareChunksByDocumentOrder);
    return sorted.map((chunk, i) => ({
      ...chunk,
      index: i + 1,
    }));
  }, [file?.chunks]);

  // Per-file min-max normalisation: best chunk in this set → 1.0, worst → 0.0.
  // Used only when there's an active search (scores are meaningful).
  const chunkScoreInfo = useMemo((): ((
    chunk: ChunkResult,
  ) => { tier: RelevanceTier; label: string } | undefined) => {
    const isSearchActive =
      Boolean(searchQuery?.trim()) && searchQuery!.trim() !== "*";
    if (!isSearchActive) return () => undefined;
    const scores = allChunks.map((c) => c.score ?? 0);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    const spread = max - min;
    return (chunk) => {
      const norm = spread > 0 ? ((chunk.score ?? 0) - min) / spread : 1;
      const tier: RelevanceTier =
        norm >= RELEVANCE_HIGH_THRESHOLD
          ? "high"
          : norm >= RELEVANCE_MED_THRESHOLD
            ? "medium"
            : "low";
      return { tier, label: `${Math.round(norm * 100)}% relevance` };
    };
  }, [allChunks, searchQuery]);

  const filterControlled = filterQuery !== undefined;
  const [internalQuery, setInternalQuery] = useState("");
  const [prevFilename, setPrevFilename] = useState(filename);
  if (!filterControlled && filename !== prevFilename) {
    setPrevFilename(filename);
    setInternalQuery("");
  }

  const localQuery = filterControlled ? filterQuery : internalQuery;
  const setLocalQuery = filterControlled
    ? (query: string) => onFilterQueryChange?.(query)
    : setInternalQuery;

  const deferredQuery = useDeferredValue(localQuery);
  const needle = deferredQuery.trim().toLowerCase();
  const chunks = needle
    ? allChunks.filter((chunk) => chunkMatches(chunk, needle))
    : allChunks;

  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    },
    [],
  );

  const handleCopy = async (text: string, listIndex: number) => {
    trackButton({
      CTA: "Copy Chunk Text",
      elementId: "copy-chunk-button",
      namespace: "knowledge",
    });
    try {
      await navigator.clipboard.writeText(text.trim());
    } catch {
      return;
    }
    setCopiedIndex(listIndex);
    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopiedIndex(null), 10_000);
  };

  const emptyHeight = compact ? "h-40" : "h-64";

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col gap-3",
        fillHeight && "h-full",
        className,
      )}
      data-testid="file-chunks-panel"
    >
      {!hideSearch && (
        <div className="flex items-center gap-2">
          <KnowledgeSearchInput
            value={localQuery}
            onSearch={setLocalQuery}
            onClear={() => setLocalQuery("")}
            hideFilterChip
            placeholder="Search chunks…"
          />
          {isSearchFetching && (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          )}
        </div>
      )}

      {isFetching ? (
        <div
          className={cn(
            "flex items-center justify-center text-muted-foreground",
            emptyHeight,
          )}
        >
          <div className="text-center">
            <Loader2 className="mx-auto mb-3 h-8 w-8 animate-spin opacity-50" />
            <p className={cn(compact ? "text-sm" : "text-lg")}>
              Loading chunks…
            </p>
          </div>
        </div>
      ) : chunks.length === 0 ? (
        <div
          className={cn(
            "flex items-center justify-center text-muted-foreground",
            emptyHeight,
          )}
        >
          <div className="text-center">
            <p className={cn("font-semibold", compact ? "text-sm" : "text-xl")}>
              No knowledge
            </p>
            <p className="mt-1 text-sm text-secondary-foreground">
              {needle
                ? "No chunks match your search."
                : "Chunks will appear here once the file is indexed."}
            </p>
          </div>
        </div>
      ) : (
        <div
          className={cn(
            "space-y-3 overflow-auto",
            fillHeight ? "min-h-0 flex-1" : compact ? "max-h-72" : "pb-6",
          )}
        >
          {chunks.map((chunk) => {
            const chunkKey = chunk.index ?? 0;
            const selected =
              selectedChunkIndex != null
                ? chunk.index === selectedChunkIndex
                : selectedPage != null && chunk.page === selectedPage;
            return (
              <FileChunkCard
                key={`${chunk.filename}-${chunkKey}`}
                chunk={chunk}
                listIndex={chunkKey}
                compact={compact}
                showContents={showContents}
                selected={selected}
                interactive={Boolean(onChunkSelect)}
                copied={copiedIndex === chunkKey}
                scoreTier={chunkScoreInfo(chunk)?.tier}
                scoreLabel={chunkScoreInfo(chunk)?.label}
                onCopy={handleCopy}
                onSelect={
                  onChunkSelect ? () => onChunkSelect(chunk) : undefined
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
