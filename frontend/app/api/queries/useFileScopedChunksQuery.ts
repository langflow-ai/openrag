import { useMemo } from "react";
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

  // Wildcard fetch for the full chunk list. Polls every 2 s until chunks appear
  // (handles files not yet queryable right after indexing), up to CHUNK_POLL_MAX_ATTEMPTS.
  const { data: allData = EMPTY_SEARCH_RESULT, isFetching: isFetchingAll } =
    useGetSearchQuery("*", queryData, {
      enabled: Boolean(filename),
      disableLiteralGate: true,
      refetchInterval: (query) => {
        const files = (query.state.data as SearchResult | undefined)?.files;
        const hasChunks = files?.some(
          (f) => f.filename === filename && (f.chunkCount ?? 0) > 0,
        );
        if (hasChunks) return false;
        const attempts = query.state.dataUpdateCount;
        return attempts < CHUNK_POLL_MAX_ATTEMPTS ? 2000 : false;
      },
    });

  // Second request for highlight fragments only. placeholderData cleared so
  // stale highlights from a prior query are never merged onto new results.
  const { data: hlData = EMPTY_SEARCH_RESULT, isFetching: isFetchingHl } =
    useGetSearchQuery(isRealQuery ? searchQuery! : "*", queryData, {
      enabled: Boolean(filename) && isRealQuery,
      placeholderData: undefined,
      disableLiteralGate: true,
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

    const hlMap = new Map<string, string[]>();
    for (const chunk of hlFile.chunks ?? []) {
      const key = chunk.chunk_id ?? chunk.id;
      if (key && chunk.highlights && chunk.highlights.length > 0) {
        hlMap.set(key, chunk.highlights);
      }
    }

    const mergedChunks: ChunkResult[] = (allFile.chunks ?? []).map((chunk) => {
      const key = chunk.chunk_id ?? chunk.id;
      const highlights = key ? (hlMap.get(key) ?? []) : [];
      return highlights.length > 0 ? { ...chunk, highlights } : chunk;
    });

    return { ...allFile, chunks: mergedChunks };
  }, [allData, hlData, filename, isRealQuery]);

  return { file, isFetching: isFetchingAll || isFetchingHl };
}
