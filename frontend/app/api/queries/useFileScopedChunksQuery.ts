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
 * Loads chunks for one filename (shared by chunks page + FileChunksPanel).
 *
 * When `searchQuery` is a non-wildcard string, two requests are fired:
 * 1. Wildcard — fetches all chunks (used when no search is active).
 * 2. Highlight fetch — fetches only the semantically matched chunks plus
 *    highlight fragments for that query.
 *
 * When a real searchQuery is active the highlight fetch result defines which
 * chunks are shown (so the count matches the knowledge page) and highlights
 * are merged in by chunk_id. When no search is active, all wildcard chunks
 * are returned as before.
 */
export function useFileScopedChunksQuery(
  filename: string | null | undefined,
  searchQuery?: string,
) {
  const isRealQuery =
    Boolean(searchQuery) &&
    searchQuery!.trim() !== "*" &&
    searchQuery!.trim() !== "";

  const queryData = filename ? fileScopedSearchQueryData(filename) : null;

  // Always fetch the complete chunk list via wildcard — this is the source of
  // truth for chunk count and the local "Search chunks" filter.
  const { data: allData = EMPTY_SEARCH_RESULT, isFetching: isFetchingAll } =
    useGetSearchQuery("*", queryData, { enabled: Boolean(filename) });

  // When there is a real search query, fire a second request (scoped to the
  // same file) purely to collect highlight fragments. This result is never used
  // for the chunk list itself — only for merging highlights below.
  //
  // placeholderData is explicitly cleared (overrides the hook default of
  // `prev => prev`) so stale highlights from a previous query are never merged
  // onto chunks belonging to a different search term.
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

    // Build chunk_id → highlights lookup from the semantic search result.
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

    // Use only the semantically matched chunks (from the highlight fetch) so
    // the count on the chunks page matches the knowledge page. Merge highlights
    // where BM25 also matched (highlights array non-empty); pure KNN hits show
    // with no highlight markup but are still included.
    const matchedChunkIds = new Set(
      (hlFile.chunks ?? []).map((c) => c.chunk_id ?? c.id).filter(Boolean),
    );
    const mergedChunks: ChunkResult[] = (allFile.chunks ?? [])
      .filter((chunk) => {
        const key = chunk.chunk_id ?? chunk.id;
        return key ? matchedChunkIds.has(key) : true;
      })
      .map((chunk) => {
        const key = chunk.chunk_id ?? chunk.id;
        const highlights = key ? (hlMap.get(key) ?? []) : [];
        return highlights.length > 0 ? { ...chunk, highlights } : chunk;
      });

    return { ...allFile, chunks: mergedChunks };
  }, [allData, hlData, filename, isRealQuery]);

  return { file, isFetching: isFetchingAll || isFetchingHl };
}
