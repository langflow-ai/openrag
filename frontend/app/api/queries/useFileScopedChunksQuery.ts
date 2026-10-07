import { useEffect, useMemo, useRef } from "react";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
import {
  EMPTY_SEARCH_RESULT,
  type File,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { fileScopedSearchQueryData } from "@/lib/file-chunks";

/**
 * Loads all chunks for one file. Shared by the chunks page and FileChunksPanel.
 *
 * A wildcard request fetches the full chunk list (source of truth for count and
 * local filtering). When `searchQuery` is set, a second parallel request fetches
 * highlight fragments, merged onto the full list by chunk_id.
 */

// Polling stops after 10 × 2 s = 20 s to handle files not yet queryable after indexing.
const CHUNK_POLL_MAX_ATTEMPTS = 10;

export function useFileScopedChunksQuery(
  filename: string | null | undefined,
  searchQuery?: string,
) {
  const isRealQuery =
    Boolean(searchQuery) &&
    searchQuery!.trim() !== "*" &&
    searchQuery!.trim() !== "";

  const queryData = filename ? fileScopedSearchQueryData(filename) : null;

  const pollBaselineRef = useRef<number | null>(null);

  // Reset baseline whenever filename changes (new file or reindex start).
  useEffect(() => {
    pollBaselineRef.current = null;
  }, [filename]);

  // Wildcard fetch for the full chunk list. Polls every 2 s until chunks appear
  // (handles files not yet queryable right after indexing), up to CHUNK_POLL_MAX_ATTEMPTS.
  const { data: allData = EMPTY_SEARCH_RESULT, isFetching: isFetchingAll } =
    useGetSearchQuery("*", queryData, {
      enabled: Boolean(filename),
      refetchInterval: (query) => {
        const files = (query.state.data as SearchResult | undefined)?.files;
        const hasChunks = files?.some(
          (f) => f.filename === filename && (f.chunkCount ?? 0) > 0,
        );
        if (hasChunks) return false;
        const total = query.state.dataUpdateCount;
        if (pollBaselineRef.current === null) {
          pollBaselineRef.current = total;
        }
        const sessionAttempts = total - pollBaselineRef.current;
        return sessionAttempts < CHUNK_POLL_MAX_ATTEMPTS ? 2000 : false;
      },
    });

  // Second request for highlight fragments only. placeholderData cleared so
  // stale highlights from a prior query are never merged onto new results.
  const { data: hlData = EMPTY_SEARCH_RESULT, isFetching: isFetchingHl } =
    useGetSearchQuery(isRealQuery ? searchQuery! : "*", queryData, {
      enabled: Boolean(filename) && isRealQuery,
      placeholderData: undefined,
    });

  const file = useMemo(() => {
    const allFile = (allData as SearchResult).files.find(
      (entry: File) => entry.filename === filename,
    );
    if (!allFile || !isRealQuery) return allFile;

    const hlFile = (hlData as SearchResult).files.find(
      (entry: File) => entry.filename === filename,
    );
    if (!hlFile) return allFile;

    const hlMap = new Map<string, { highlights: string[]; score: number }>();
    for (const chunk of hlFile.chunks ?? []) {
      const key = chunk.chunk_id ?? chunk.id;
      if (key) {
        hlMap.set(key, {
          highlights: chunk.highlights ?? [],
          score: chunk.score,
        });
      }
    }

    const mergedChunks: ChunkResult[] = (allFile.chunks ?? []).map((chunk) => {
      const key = chunk.chunk_id ?? chunk.id;
      const hl = key ? hlMap.get(key) : undefined;
      if (!hl) return chunk;
      return {
        ...chunk,
        ...(hl.highlights.length > 0 ? { highlights: hl.highlights } : {}),
        score: hl.score,
      };
    });

    return { ...allFile, chunks: mergedChunks };
  }, [allData, hlData, filename, isRealQuery]);

  return { file, isFetching: isFetchingAll, isSearchFetching: isFetchingHl };
}
