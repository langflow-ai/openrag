import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { apiClient, isRequestCancelled } from "@/lib/api-client";
import { SEARCH_CONSTANTS, SEARCH_SCORING } from "@/lib/constants";
import {
  buildSearchPayloadFilters,
  type FilterInput,
} from "@/lib/filter-normalization";

export interface SearchPayload {
  query: string;
  limit: number;
  scoreThreshold: number;
  filters?: FilterInput;
  resultMode?: "chunks" | "knowledge_sources" | "website_pages";
}

export interface ChunkResult {
  filename: string;
  mimetype: string;
  page: number;
  text: string;
  /** OpenSearch highlight fragments with matched terms wrapped in `<mark>` tags. Empty when no keyword match. */
  highlights?: string[];
  score: number;
  /** Normalized score [0, 1] relative to the active search result set. */
  normalizedScore?: number;
  source_url?: string;
  owner?: string;
  owner_name?: string;
  owner_email?: string;
  file_size?: number;
  connector_type?: string;
  embedding_model?: string;
  embedding_dimensions?: number;
  parser?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  chunk_id?: string;
  id?: string;
  index?: number;
  allowed_users?: string[];
  allowed_groups?: string[];
  document_id?: string;
  web_source_id?: string;
  web_page_id?: string;
  web_page_depth?: number;
  web_child_count?: number;
  canonical_url?: string;
  status?: File["status"];
  error?: string;
  chunk_count?: number;
}

export type RelevanceTier = "high" | "medium" | "low";
export interface ChunkTiers {
  high: number;
  medium: number;
  low: number;
}

export interface File {
  filename: string;
  mimetype: string;
  chunkCount?: number;
  /** Average raw score across matched chunks for this file. */
  avgScore?: number;
  /** Highest min-max normalised chunk score [0, 1] for this file. Undefined for wildcard queries. */
  maxScore?: number;
  /** Relevance tier derived from maxScore. */
  relevanceTier?: RelevanceTier;
  /** Count of matched chunks per tier, shown in the relevance tooltip. */
  chunkTiers?: ChunkTiers;
  /** True if top match for this file was semantically relevant (vector match without keyword highlights). */
  isSemanticMatch?: boolean;
  source_url: string;
  owner?: string;
  owner_name?: string;
  owner_email?: string;
  size: number;
  connector_type: string;
  embedding_model?: string;
  embedding_dimensions?: number;
  status?:
    | "processing"
    | "active"
    | "unavailable"
    | "failed"
    | "cancelled"
    | "skipped"
    | "hidden"
    | "sync"
    | "disabled";
  error?: string;
  /** Skip reason from the backend (e.g. "duplicate_content", "deleted_at_source"). Only set when status === "skipped". */
  skip_reason?: string;
  /** Human-readable warning for skipped rows. */
  warning?: string;
  task_id?: string;
  chunks?: ChunkResult[];
  allowed_users?: string[];
  allowed_groups?: string[];
  document_id?: string;
  web_source_id?: string;
  web_page_id?: string;
  web_page_depth?: number;
  web_child_count?: number;
}

/** Non-fatal backend signal, e.g. an embedding provider is unavailable. Results still return via keyword matching. */
export interface SearchWarning {
  code: string;
  models?: string[];
  semantic_search_available?: boolean;
  message?: string;
}

export interface SearchResult {
  files: File[];
  warnings: SearchWarning[];
}

export interface SearchResultDisplayOptions {
  groupBy?: "filename" | "document_id";
  resultMode?: "chunks" | "knowledge_sources" | "website_pages";
}

const EMPTY_SEARCH_RESULT: SearchResult = { files: [], warnings: [] };

export { EMPTY_SEARCH_RESULT };

/** Min-max normalised score thresholds for bucketing chunks into High / Medium / Low tiers. */
export const RELEVANCE_HIDE_THRESHOLD = SEARCH_SCORING.relevance_hide_threshold;
export const RELEVANCE_HIGH_THRESHOLD = SEARCH_SCORING.relevance_high_threshold;
export const RELEVANCE_MED_THRESHOLD = SEARCH_SCORING.relevance_med_threshold;

const getFileIdentity = (
  chunk: ChunkResult,
  groupBy: SearchResultDisplayOptions["groupBy"],
): string => {
  if (groupBy === "document_id" && chunk.document_id) {
    return chunk.document_id;
  }
  const normalizedFilename = chunk.filename?.trim();
  if (normalizedFilename) {
    return normalizedFilename;
  }

  const normalizedSourceUrl = chunk.source_url?.trim();
  if (normalizedSourceUrl) {
    return normalizedSourceUrl;
  }

  return "Untitled source";
};

export const useGetSearchQuery = (
  query: string,
  queryData?: ParsedQueryData | null,
  options?: Omit<
    UseQueryOptions<SearchResult, Error, SearchResult, unknown[]>,
    "queryKey" | "queryFn"
  >,
  displayOptions: SearchResultDisplayOptions = {},
) => {
  const queryClient = useQueryClient();

  const effectiveQuery = query || queryData?.query || "*";
  const normalizedQuery = effectiveQuery.trim();

  async function getFiles(): Promise<SearchResult> {
    try {
      const isWildcardQuery =
        effectiveQuery.trim() === "*" || effectiveQuery.trim() === "";
      const searchLimit = isWildcardQuery
        ? SEARCH_CONSTANTS.WILDCARD_QUERY_LIMIT
        : queryData?.limit || 100;

      const baseScoreThreshold =
        queryData?.scoreThreshold ?? SEARCH_CONSTANTS.DEFAULT_SCORE_THRESHOLD;
      const isShortSingleTokenQuery =
        normalizedQuery !== "*" &&
        normalizedQuery.length > 0 &&
        normalizedQuery.length <= 4 &&
        !normalizedQuery.includes(" ");
      const scoreThreshold = isShortSingleTokenQuery
        ? Math.min(baseScoreThreshold, 1.0)
        : baseScoreThreshold;

      const searchPayload: SearchPayload = {
        query: effectiveQuery,
        limit: searchLimit,
        scoreThreshold,
        resultMode: displayOptions.resultMode,
      };
      if (queryData?.filters) {
        searchPayload.filters =
          buildSearchPayloadFilters(queryData.filters) ?? undefined;
      }

      const response = await apiClient.post(`/search`, searchPayload);

      if (response.status < 200 || response.status >= 300) {
        const errorData =
          response.data && typeof response.data === "object"
            ? (response.data as { error?: string })
            : { error: "Unknown error" };
        throw new Error(
          errorData.error || `Search failed with status ${response.status}`,
        );
      }

      const data = response.data;
      const fileMap = new Map<
        string,
        {
          filename: string;
          mimetype: string;
          chunks: ChunkResult[];
          totalScore: number;
          source_url?: string;
          owner?: string;
          owner_name?: string;
          owner_email?: string;
          file_size?: number;
          connector_type?: string;
          embedding_model?: string;
          embedding_dimensions?: number;
          allowed_users?: string[];
          allowed_groups?: string[];
          document_id?: string;
          web_source_id?: string;
          web_page_id?: string;
          web_page_depth?: number;
          web_child_count?: number;
          canonical_url?: string;
          status?: File["status"];
          error?: string;
          chunk_count?: number;
        }
      >();

      (data.results || []).forEach((chunk: ChunkResult) => {
        const fileIdentity = getFileIdentity(chunk, displayOptions.groupBy);
        // Preserve highlights on the chunk object itself — they are per-chunk,
        // not per-file, so we carry them through rather than aggregating.
        const chunkWithHighlights: ChunkResult = {
          ...chunk,
          highlights: Array.isArray(chunk.highlights) ? chunk.highlights : [],
        };
        const existing = fileMap.get(fileIdentity);
        if (existing) {
          existing.chunks.push(chunkWithHighlights);
          existing.totalScore += chunk.score ?? 0;
          if (!existing.embedding_model && chunk.embedding_model) {
            existing.embedding_model = chunk.embedding_model;
          }
          if (
            existing.embedding_dimensions == null &&
            typeof chunk.embedding_dimensions === "number"
          ) {
            existing.embedding_dimensions = chunk.embedding_dimensions;
          }
          if (typeof chunk.chunk_count === "number") {
            existing.chunk_count = chunk.chunk_count;
          }
          if (typeof chunk.web_child_count === "number") {
            existing.web_child_count = chunk.web_child_count;
          }
        } else {
          fileMap.set(fileIdentity, {
            filename:
              displayOptions.groupBy === "document_id"
                ? chunk.filename || fileIdentity
                : fileIdentity,
            mimetype: chunk.mimetype,
            chunks: [chunkWithHighlights],
            totalScore: chunk.score ?? 0,
            source_url: chunk.source_url,
            owner: chunk.owner,
            owner_name: chunk.owner_name,
            owner_email: chunk.owner_email,
            file_size: chunk.file_size,
            connector_type: chunk.connector_type,
            embedding_model: chunk.embedding_model,
            embedding_dimensions: chunk.embedding_dimensions,
            allowed_users: chunk.allowed_users || [],
            allowed_groups: chunk.allowed_groups || [],
            document_id: chunk.document_id,
            web_source_id: chunk.web_source_id,
            web_page_id: chunk.web_page_id,
            web_page_depth: chunk.web_page_depth,
            web_child_count: chunk.web_child_count,
            canonical_url: chunk.canonical_url,
            status: chunk.status,
            error: chunk.error,
            chunk_count: chunk.chunk_count,
          });
        }
      });

      const warnings: SearchWarning[] = Array.isArray(data.warnings)
        ? data.warnings
        : [];

      // Min-max normalise: best chunk → 1.0, worst → 0.0. Single result → 1.0 (avoids / 0).
      const allChunks = Array.from(fileMap.values()).flatMap((f) => f.chunks);
      const rawScores = allChunks.map((c) => c.score ?? 0);
      const globalMin = Math.min(...rawScores);
      const globalMax = Math.max(...rawScores);
      const scoreSpread = globalMax - globalMin;

      const normalise = (raw: number): number =>
        scoreSpread > 0 ? (raw - globalMin) / scoreSpread : 1;

      const toTier = (norm: number): RelevanceTier =>
        norm >= RELEVANCE_HIGH_THRESHOLD
          ? "high"
          : norm >= RELEVANCE_MED_THRESHOLD
            ? "medium"
            : "low";

      const files: File[] = Array.from(fileMap.values()).map((file) => {
        const chunksWithNorm = file.chunks.map((c) => ({
          ...c,
          normalizedScore: normalise(c.score ?? 0),
        }));
        const normScores = chunksWithNorm.map((c) => c.normalizedScore ?? 0);
        const fileMaxNorm = Math.max(...normScores);
        const chunkTiers: ChunkTiers = { high: 0, medium: 0, low: 0 };
        for (const norm of normScores) {
          chunkTiers[toTier(norm)]++;
        }
        const topChunk = chunksWithNorm.reduce(
          (best, c) => ((c.score ?? 0) > (best.score ?? 0) ? c : best),
          chunksWithNorm[0],
        );
        const hasHighlights =
          Array.isArray(topChunk?.highlights) &&
          topChunk.highlights.length > 0 &&
          topChunk.highlights.some((h) => h.includes("<mark>"));
        const isSemanticMatch = (topChunk?.score ?? 0) > 0 && !hasHighlights;

        return {
          filename: file.filename,
          mimetype: file.mimetype,
          chunkCount: file.chunk_count ?? file.chunks.length,
          avgScore: file.totalScore / file.chunks.length,
          maxScore: fileMaxNorm,
          relevanceTier: toTier(fileMaxNorm),
          chunkTiers,
          isSemanticMatch,
          source_url: file.source_url || "",
          owner: file.owner || "",
          owner_name: file.owner_name || "",
          owner_email: file.owner_email || "",
          size: file.file_size || 0,
          connector_type: file.connector_type || "local",
          embedding_model: file.embedding_model,
          embedding_dimensions: file.embedding_dimensions,
          chunks: chunksWithNorm,
          allowed_users: file.allowed_users || [],
          allowed_groups: file.allowed_groups || [],
          document_id: file.document_id,
          web_source_id: file.web_source_id,
          web_page_id: file.web_page_id,
          web_page_depth: file.web_page_depth,
          web_child_count: file.web_child_count,
          status: file.status,
          error: file.error,
        };
      });

      return { files, warnings };
    } catch (error) {
      // Cancellation is expected (not an error); still re-throw it below
      if (!isRequestCancelled(error)) {
        console.error("Error getting files", error);
      }
      // Re-throw the error so React Query can handle it and trigger onError callbacks
      throw error;
    }
  }

  return useQuery(
    {
      queryKey: ["search", queryData, query, displayOptions],
      placeholderData: (prev) => prev,
      staleTime: 0,
      queryFn: getFiles,
      retry: false,
      ...options,
    },
    queryClient,
  );
};
