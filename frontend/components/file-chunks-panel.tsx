"use client";

import { Check, Copy, Eye, EyeOff, Loader2 } from "lucide-react";
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
  /**
   * When true (and a searchQuery is active), low-relevance chunks are hidden by default.
   * The user can toggle them back on via the "Show all" button.
   */
  hideIrrelevant?: boolean;
}

function chunkMatches(
  chunk: ChunkResult,
  needle: string,
  isSearchActive?: boolean,
): boolean {
  if (isSearchActive) {
    return (
      (chunk.score ?? 0) > 0 ||
      Boolean(chunk.highlights && chunk.highlights.length > 0)
    );
  }
  const text = chunk.text.toLowerCase();
  const indexStr = chunk.index != null ? String(chunk.index) : "";
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

const SEMANTIC_SCORE_TIER_CLASS: Record<RelevanceTier, string> = {
  high: "border-indigo-500 text-indigo-700 bg-indigo-50 dark:border-indigo-400 dark:text-indigo-300 dark:bg-indigo-950/40",
  medium:
    "border-purple-500 text-purple-700 bg-purple-50 dark:border-purple-400 dark:text-purple-300 dark:bg-purple-950/40",
  low: "border-violet-400 text-violet-700 bg-violet-50 dark:border-violet-500/40 dark:text-violet-300 dark:bg-violet-950/30",
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
  isSemanticMatch,
  searchQuery,
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
  isSemanticMatch?: boolean;
  searchQuery?: string;
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
        <div className="flex items-center gap-1.5 shrink-0">
          {isSemanticMatch ? (
            <Badge
              variant="secondary"
              className={cn(
                "text-xxs border shrink-0",
                scoreTier
                  ? SEMANTIC_SCORE_TIER_CLASS[scoreTier]
                  : SEMANTIC_SCORE_TIER_CLASS["high"],
              )}
            >
              Semantically relevant
              {scoreLabel ? ` (${scoreLabel.replace(" relevance", "")})` : ""}
            </Badge>
          ) : (
            scoreLabel && (
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
            )
          )}
        </div>
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
            isSemanticMatch={isSemanticMatch}
            searchQuery={searchQuery}
            scoreTier={scoreTier}
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
 * Loads this file's chunks once, then filters locally so paste-from-chunk works.
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
  hideIrrelevant = false,
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

  const chunkScoreInfo = useMemo((): ((
    chunk: ChunkResult,
  ) =>
    | { tier: RelevanceTier; label: string; isSemanticMatch: boolean }
    | undefined) => {
    const isSearchActive =
      Boolean(searchQuery?.trim()) && searchQuery!.trim() !== "*";
    if (!isSearchActive) return () => undefined;
    const scores = allChunks.map((c) => c.score ?? 0);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    const spread = max - min;
    return (chunk) => {
      const rawScore = chunk.score ?? 0;
      if (rawScore === 0) {
        return {
          tier: "low",
          label: "0% relevance",
          isSemanticMatch: false,
        };
      }
      const hasGlobalNorm =
        typeof chunk.normalizedScore === "number" && chunk.normalizedScore > 0;
      const norm = hasGlobalNorm
        ? chunk.normalizedScore!
        : spread > 0
          ? (rawScore - min) / spread
          : rawScore > 0
            ? 1
            : 0;
      const tier: RelevanceTier =
        norm >= RELEVANCE_HIGH_THRESHOLD
          ? "high"
          : norm >= RELEVANCE_MED_THRESHOLD
            ? "medium"
            : "low";
      const hasHighlights =
        Array.isArray(chunk.highlights) &&
        chunk.highlights.length > 0 &&
        chunk.highlights.some((h) => h.includes("<mark>"));
      // Guard on isSearchFetching: highlights are [] mid-flight, which would
      // incorrectly flag every scored chunk as semantic before marks arrive.
      const isSemanticMatch =
        rawScore > 0 && !hasHighlights && !isSearchFetching;
      return {
        tier,
        label: `${Math.max(1, Math.round(norm * 100))}% relevance`,
        isSemanticMatch,
      };
    };
  }, [allChunks, searchQuery, isSearchFetching]);

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

  const isSearchActive =
    Boolean(searchQuery?.trim()) && searchQuery!.trim() !== "*";
  const [showingAll, setShowingAll] = useState(false);

  const [prevSearchQuery, setPrevSearchQuery] = useState(searchQuery);
  if (searchQuery !== prevSearchQuery) {
    setPrevSearchQuery(searchQuery);
    setShowingAll(false);
  }

  const textFilteredChunks = needle
    ? allChunks.filter((chunk) => chunkMatches(chunk, needle, isSearchActive))
    : allChunks;

  const relevanceFilterActive = hideIrrelevant && isSearchActive && !showingAll;

  // Only chunks the backend scored (score > 0); zero-score chunks are from the
  // wildcard base fetch and were not returned by the search query.
  const scoredChunks = useMemo(
    () =>
      isSearchActive
        ? textFilteredChunks.filter((c) => (c.score ?? 0) > 0)
        : textFilteredChunks,
    [isSearchActive, textFilteredChunks],
  );

  const totalLowCount = useMemo(() => {
    if (!hideIrrelevant || !isSearchActive) return 0;
    return scoredChunks.filter((c) => chunkScoreInfo(c)?.tier === "low").length;
  }, [hideIrrelevant, isSearchActive, scoredChunks, chunkScoreInfo]);

  const chunks = useMemo(() => {
    const base = isSearchActive ? scoredChunks : textFilteredChunks;
    const sorted = isSearchActive
      ? [...base].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
      : base;

    if (!relevanceFilterActive) return sorted;

    // Always keep at least one chunk visible — sorted[0] is the highest scorer.
    const nonLow = sorted.filter((c) => chunkScoreInfo(c)?.tier !== "low");
    if (nonLow.length > 0) return nonLow;
    return sorted.slice(0, 1); // all low — show only the best one
  }, [
    relevanceFilterActive,
    scoredChunks,
    textFilteredChunks,
    chunkScoreInfo,
    isSearchActive,
  ]);

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

      {hideIrrelevant && isSearchActive && totalLowCount > 0 && (
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md border border-border/50 bg-muted/60 px-3 py-2 text-xs text-muted-foreground hover:bg-muted transition-colors"
          onClick={() => setShowingAll((prev) => !prev)}
        >
          {showingAll ? (
            <Eye className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <EyeOff className="h-3.5 w-3.5 shrink-0" />
          )}
          <span className="flex-1 text-left">
            {showingAll
              ? "Showing all chunks including low-relevance"
              : (() => {
                  // When every scored chunk is low, the best one is still shown —
                  // so only (totalLowCount - 1) are actually hidden.
                  const allLow = totalLowCount === scoredChunks.length;
                  const hiddenCount = allLow
                    ? totalLowCount - 1
                    : totalLowCount;
                  if (hiddenCount === 0)
                    return "Showing best result (low relevance)";
                  return `${hiddenCount} low-relevance chunk${hiddenCount !== 1 ? "s" : ""} hidden`;
                })()}
          </span>
          <span className="flex items-center gap-1 font-medium text-foreground">
            {showingAll ? (
              <>
                <EyeOff className="h-3 w-3" />
                Hide low-relevance
              </>
            ) : (
              <>
                <Eye className="h-3 w-3" />
                Show all
              </>
            )}
          </span>
        </button>
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
                isSemanticMatch={chunkScoreInfo(chunk)?.isSemanticMatch}
                searchQuery={searchQuery}
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
