import { useQuery } from "@tanstack/react-query";
import { resolveScoreThreshold } from "@/app/api/queries/useGetSearchQuery";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { apiClient } from "@/lib/api-client";
import { SEARCH_CONSTANTS } from "@/lib/constants";
import {
  buildSearchPayloadFilters,
  type FilterInput,
} from "@/lib/filter-normalization";

/** Wait after the last keystroke before the cheap keyword request. */
export const SUGGEST_KEYWORD_DEBOUNCE_MS = 180;
/** Wait before the embedding-backed request (a partial word has no meaning). */
export const SUGGEST_SEMANTIC_DEBOUNCE_MS = 450;
export const SUGGEST_MIN_CHARS = 2;
/** Matches the server's MAX_QUERY_LENGTH; longer input is truncated there. */
export const SUGGEST_MAX_CHARS = 100;
export const SUGGEST_SEMANTIC_MIN_CHARS = 3;
const SUGGEST_STALE_TIME_MS = 30_000;

export interface SearchSuggestion {
  text: string;
  files: number;
  chunks: number;
}

export interface SuggestPreview {
  /** One line; `keyword` previews wrap matched terms in `<mark>`. */
  text: string;
  kind: "keyword" | "semantic";
}

export interface SuggestFile {
  filename: string;
  mimetype?: string | null;
  connector_type?: string | null;
  preview: SuggestPreview | null;
}

export interface SearchSuggestResult {
  phase: "keyword" | "semantic";
  query: string;
  suggestions: SearchSuggestion[];
  files: SuggestFile[];
}

async function fetchSuggestions(
  query: string,
  semantic: boolean,
  filters: FilterInput | undefined,
  scoreThreshold: number,
  signal: AbortSignal,
): Promise<SearchSuggestResult> {
  const response = await apiClient.post(
    "/search/suggest",
    {
      query,
      semantic,
      filters: buildSearchPayloadFilters(filters) ?? {},
      scoreThreshold,
    },
    { signal },
  );
  if (response.status < 200 || response.status >= 300) {
    throw new Error(`Suggestions failed with status ${response.status}`);
  }
  return response.data as SearchSuggestResult;
}

export interface UseSearchSuggestionsResult {
  data: SearchSuggestResult | undefined;
  /** True while the semantic refinement for the current text is still pending. */
  isRefining: boolean;
  isFetching: boolean;
  /** The keyword request failed and there is nothing to show. */
  isError: boolean;
}

/**
 * Search-as-you-type suggestions in two phases.
 *
 * Phase 1 (keyword) runs on a short debounce and never touches the embedding
 * provider. Phase 2 (semantic) waits for a longer idle period, or fires at
 * once on a word boundary (trailing space). The semantic result replaces the
 * keyword one when it lands. Both are cached by TanStack Query (and again on
 * the server), so retyping or backspacing costs no network call.
 */
export function useSearchSuggestions(
  rawQuery: string,
  filters: FilterInput | undefined,
  enabled = true,
  baseScoreThreshold: number = SEARCH_CONSTANTS.DEFAULT_SCORE_THRESHOLD,
): UseSearchSuggestionsResult {
  // Mirror the server's normalization (whitespace collapse, length cap) so the
  // returned query matches what was typed and equivalent inputs share a cache
  // entry. Spread to count code points like the server does.
  const trimmed = [...rawQuery.trim().replace(/\s+/g, " ")]
    .slice(0, SUGGEST_MAX_CHARS)
    .join("");
  const keywordQuery = useDebouncedValue(trimmed, SUGGEST_KEYWORD_DEBOUNCE_MS);
  const atWordBoundary = rawQuery.endsWith(" ");
  const semanticQuery = useDebouncedValue(
    trimmed,
    atWordBoundary ? 0 : SUGGEST_SEMANTIC_DEBOUNCE_MS,
  );

  const filtersKey = JSON.stringify(buildSearchPayloadFilters(filters) ?? {});

  const keywordThreshold = resolveScoreThreshold(
    keywordQuery,
    baseScoreThreshold,
  );
  const keyword = useQuery({
    queryKey: ["search-suggest", "keyword", keywordQuery, filtersKey],
    queryFn: ({ signal }) =>
      fetchSuggestions(keywordQuery, false, filters, keywordThreshold, signal),
    enabled: enabled && keywordQuery.length >= SUGGEST_MIN_CHARS,
    staleTime: SUGGEST_STALE_TIME_MS,
    retry: false,
  });

  const semanticEnabled =
    enabled && semanticQuery.length >= SUGGEST_SEMANTIC_MIN_CHARS;
  const scoreThreshold = resolveScoreThreshold(
    semanticQuery,
    baseScoreThreshold,
  );
  const semantic = useQuery({
    queryKey: [
      "search-suggest",
      "semantic",
      semanticQuery,
      filtersKey,
      scoreThreshold,
    ],
    queryFn: ({ signal }) =>
      fetchSuggestions(semanticQuery, true, filters, scoreThreshold, signal),
    enabled: semanticEnabled,
    staleTime: SUGGEST_STALE_TIME_MS,
    retry: false,
  });

  return {
    ...mergePhases({
      trimmed,
      keywordQuery,
      semanticQuery,
      semanticEnabled,
      keyword,
      semantic,
    }),
    isFetching: keyword.isFetching || semantic.isFetching,
  };
}

interface PhaseState {
  data: SearchSuggestResult | undefined;
  isError: boolean;
  isFetching: boolean;
}

function mergePhases({
  trimmed,
  keywordQuery,
  semanticQuery,
  semanticEnabled,
  keyword,
  semantic,
}: {
  trimmed: string;
  keywordQuery: string;
  semanticQuery: string;
  semanticEnabled: boolean;
  keyword: PhaseState;
  semantic: PhaseState;
}): Omit<UseSearchSuggestionsResult, "isFetching"> {
  // Only trust results that match the text currently shown, so a late response
  // or a still-debouncing query never displays another search's suggestions.
  const semanticCurrent =
    semantic.data && semanticQuery === trimmed ? semantic.data : undefined;
  const keywordCurrent =
    keyword.data && keywordQuery === trimmed ? keyword.data : undefined;
  const data = semanticCurrent ?? keywordCurrent;
  const visibleData = trimmed.length >= SUGGEST_MIN_CHARS ? data : undefined;

  const isRefining =
    semanticEnabled &&
    !semanticCurrent &&
    !semantic.isError &&
    (semanticQuery !== trimmed || semantic.isFetching);

  return {
    data: visibleData,
    isRefining,
    isError: !visibleData && (keyword.isError || semantic.isError),
  };
}
