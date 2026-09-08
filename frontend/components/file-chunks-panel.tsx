"use client";

import { Check, Copy, Loader2 } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useFileScopedChunksQuery } from "@/app/api/queries/useFileScopedChunksQuery";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
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
}

function chunkMatches(chunk: ChunkResult, needle: string): boolean {
  return (
    chunk.text.toLowerCase().includes(needle) ||
    (chunk.index != null && String(chunk.index).includes(needle))
  );
}

function FileChunkCard({
  chunk,
  listIndex,
  compact,
  showContents,
  selected,
  interactive,
  copied,
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
        {typeof chunk.score === "number" && chunk.score > 0 && (
          <Badge
            variant="secondary"
            className="shrink-0 text-xxs bg-background text-foreground border border-border"
          >
            {chunk.score.toFixed(2)} score
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
          {chunk.text}
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
}: FileChunksPanelProps) {
  const { file, isFetching } = useFileScopedChunksQuery(filename);
  const allChunks = useMemo(() => {
    const sorted = [...(file?.chunks ?? [])].sort(compareChunksByDocumentOrder);
    return sorted.map((chunk, i) => ({
      ...chunk,
      index: i + 1,
    }));
  }, [file?.chunks]);

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
        <KnowledgeSearchInput
          value={localQuery}
          onSearch={setLocalQuery}
          onClear={() => setLocalQuery("")}
          hideFilterChip
          placeholder="Search chunks…"
        />
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
