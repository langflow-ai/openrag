import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
import {
  EMPTY_SEARCH_RESULT,
  type File,
  type RelevanceTier,
  type SearchResult,
  useGetSearchQuery,
} from "@/app/api/queries/useGetSearchQuery";
import { fileScopedSearchQueryData } from "@/lib/file-chunks";

// Polling stops after 10 × 2 s = 20 s for files not yet queryable after indexing.
const CHUNK_POLL_MAX_ATTEMPTS = 10;

export function useFileScopedChunksQuery(
  filename: string | null | undefined,
  searchQuery?: string,
) {
  const isRealQuery =
    Boolean(searchQuery) &&
    searchQuery!.trim() !== "*" &&
    searchQuery!.trim() !== "";

  const queryClient = useQueryClient();
  const queryData = filename ? fileScopedSearchQueryData(filename) : null;

  const pollBaselineRef = useRef<number | null>(null);

  useEffect(() => {
    pollBaselineRef.current = null;
  }, [filename]);

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

  // placeholderData cleared so stale highlights from a prior query are never shown.
  const {
    data: hlData = EMPTY_SEARCH_RESULT,
    isFetching: isFetchingHl,
    isSuccess: isHlSuccess,
  } = useGetSearchQuery(isRealQuery ? searchQuery! : "*", queryData, {
    enabled: Boolean(filename) && isRealQuery,
    placeholderData: undefined,
  });

  // hlSettled goes true once hlData has resolved for the current query, and resets
  // on query change. Used to gate hlFile scores/badges so they never show mid-flight.
  const prevHlQueryRef = useRef<string | undefined>(undefined);
  const [hlSettled, setHlSettled] = useState(false);
  if (isRealQuery && searchQuery !== prevHlQueryRef.current) {
    prevHlQueryRef.current = searchQuery;
    if (hlSettled) setHlSettled(false);
  }
  useEffect(() => {
    if (isHlSuccess && !isFetchingHl) setHlSettled(true);
  }, [isHlSuccess, isFetchingHl]);

  const file = useMemo(() => {
    const allFile = (allData as SearchResult).files.find(
      (entry: File) => entry.filename === filename,
    );
    if (!allFile || !isRealQuery) return allFile;

    const hlFile = (hlData as SearchResult).files.find(
      (entry: File) => entry.filename === filename,
    );

    // Scan cache for a real (non-wildcard, non-file-scoped) search entry — the only
    // source of globally-comparable normalised scores that match what the file row shows.
    const globalCacheEntries = queryClient.getQueriesData<SearchResult>({
      queryKey: ["search"],
    });
    let globalFile: File | undefined;
    for (const [cacheKey, result] of globalCacheEntries) {
      const keyQueryData = (cacheKey as unknown[])[1] as
        | { filters?: { data_sources?: string[] }; query?: string }
        | null
        | undefined;
      const keyQueryString = (cacheKey as unknown[])[2] as string | undefined;

      const isWildcard =
        !keyQueryString ||
        keyQueryString.trim() === "" ||
        keyQueryString.trim() === "*";
      if (isWildcard) continue;

      const isFileScoped =
        Array.isArray(keyQueryData?.filters?.data_sources) &&
        keyQueryData!.filters!.data_sources!.length > 0;
      if (isFileScoped) continue;

      const match = result?.files?.find((f) => f.filename === filename);
      if (match) {
        globalFile = match;
        break;
      }
    }

    // Scores come from globalFile (globally normalised, matches the file-row %).
    // Falls back to hlFile once hlSettled when globalFile is absent (direct nav).
    const scoreMap = new Map<
      string,
      { score: number; normalizedScore?: number }
    >();
    const scoreSource = globalFile ?? (hlSettled ? hlFile : undefined);
    if (scoreSource) {
      for (const chunk of scoreSource.chunks ?? []) {
        const key = chunk.chunk_id ?? chunk.id;
        if (key) {
          scoreMap.set(key, {
            score: chunk.score,
            normalizedScore: chunk.normalizedScore,
          });
        }
      }
    }

    const hlMap = new Map<string, string[]>();
    if (hlFile) {
      for (const chunk of hlFile.chunks ?? []) {
        const key = chunk.chunk_id ?? chunk.id;
        if (key) hlMap.set(key, chunk.highlights ?? []);
      }
    }

    const mergedChunks: ChunkResult[] = (allFile.chunks ?? []).map((chunk) => {
      const key = chunk.chunk_id ?? chunk.id;
      const scoreEntry = key ? scoreMap.get(key) : undefined;
      const highlights = (key ? hlMap.get(key) : undefined) ?? [];
      return {
        ...chunk,
        highlights,
        score: scoreEntry?.score ?? 0,
        normalizedScore: scoreEntry?.normalizedScore ?? 0,
      };
    });

    const metaSource = globalFile ?? (hlSettled ? hlFile : undefined);
    const maxScore = metaSource?.maxScore;
    const relevanceTier = metaSource?.relevanceTier as
      | RelevanceTier
      | undefined;
    const isSemanticMatch = metaSource?.isSemanticMatch;

    return {
      ...allFile,
      maxScore,
      relevanceTier,
      isSemanticMatch,
      chunks: mergedChunks,
    };
  }, [
    allData,
    hlData,
    filename,
    isRealQuery,
    queryClient,
    searchQuery,
    hlSettled,
  ]);

  return { file, isFetching: isFetchingAll, isSearchFetching: isFetchingHl };
}
