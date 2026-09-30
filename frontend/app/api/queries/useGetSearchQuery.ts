import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { SEARCH_CONSTANTS } from "@/lib/constants";
import { buildSearchPayloadFilters } from "@/lib/filter-normalization";

export interface SearchPayload {
  query: string;
  limit: number;
  scoreThreshold: number;
  filters?: {
    data_sources?: string[];
    document_types?: string[];
    owners?: string[];
    connector_types?: string[];
  };
}

export interface ChunkResult {
  filename: string;
  mimetype: string;
  page: number;
  text: string;
  /** OpenSearch highlight fragments with matched terms wrapped in `<mark>` tags. Empty when no keyword match. */
  highlights?: string[];
  score: number;
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
  /** Highest min-max normalised chunk score [0, 1] for this file. Undefined for wildcard queries. */
  maxScore?: number;
  /** Relevance tier derived from maxScore. */
  relevanceTier?: RelevanceTier;
  /** Count of matched chunks per tier, shown in the relevance tooltip. */
  chunkTiers?: ChunkTiers;
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
    | "sync";
  error?: string;
  /** Skip reason from the backend (e.g. "duplicate_content", "deleted_at_source"). Only set when status === "skipped". */
  skip_reason?: string;
  /** Human-readable warning for skipped rows. */
  warning?: string;
  task_id?: string;
  chunks?: ChunkResult[];
  allowed_users?: string[];
  allowed_groups?: string[];
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

const EMPTY_SEARCH_RESULT: SearchResult = { files: [], warnings: [] };

export { EMPTY_SEARCH_RESULT };

/** Min-max normalised score thresholds for bucketing chunks into High / Medium / Low tiers. */
export const RELEVANCE_HIGH_THRESHOLD = 0.65;
export const RELEVANCE_MED_THRESHOLD = 0.35;

/** Stopwords excluded from the literal-match gate to avoid false passes on tokens like "the" or "your". */
const GATE_STOPWORDS = new Set([
  "a",
  "an",
  "the",
  "and",
  "or",
  "but",
  "in",
  "on",
  "at",
  "to",
  "for",
  "of",
  "with",
  "by",
  "from",
  "is",
  "it",
  "its",
  "was",
  "are",
  "were",
  "be",
  "been",
  "being",
  "have",
  "has",
  "had",
  "do",
  "does",
  "did",
  "will",
  "would",
  "could",
  "should",
  "may",
  "might",
  "shall",
  "can",
  "not",
  "no",
  "nor",
  "so",
  "yet",
  "both",
  "either",
  "neither",
  "this",
  "that",
  "these",
  "those",
  "my",
  "your",
  "his",
  "her",
  "our",
  "their",
  "its",
  "i",
  "you",
  "he",
  "she",
  "we",
  "they",
  "me",
  "him",
  "us",
  "them",
  "what",
  "which",
  "who",
  "whom",
  "how",
  "when",
  "where",
  "why",
  "all",
  "each",
  "every",
  "any",
  "some",
  "such",
  "than",
  "then",
  "as",
  "if",
  "up",
  "out",
  "about",
  "into",
  "through",
  "during",
  "before",
  "after",
  "above",
  "below",
  "between",
  "own",
  "same",
  "other",
]);

const getFileIdentity = (chunk: ChunkResult): string => {
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
  > & {
    /** Skip the literal-match gate. Set on the single-file chunks view where the user navigated deliberately. */
    disableLiteralGate?: boolean;
  },
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
      const dynamicScoreThreshold = isShortSingleTokenQuery
        ? Math.min(baseScoreThreshold, 1.0)
        : baseScoreThreshold;

      const searchPayload: SearchPayload = {
        query: effectiveQuery,
        limit: searchLimit,
        scoreThreshold: dynamicScoreThreshold,
      };
      if (queryData?.filters) {
        searchPayload.filters =
          buildSearchPayloadFilters(queryData.filters) ?? undefined;
      }

      const response = await fetch(`/api/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(searchPayload),
      });

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ error: "Unknown error" }));
        throw new Error(
          errorData.error || `Search failed with status ${response.status}`,
        );
      }

      const data = await response.json();
      const fileMap = new Map<
        string,
        {
          filename: string;
          mimetype: string;
          chunks: ChunkResult[];
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
        }
      >();

      (data.results || []).forEach((chunk: ChunkResult) => {
        const fileIdentity = getFileIdentity(chunk);
        const chunkWithHighlights: ChunkResult = {
          ...chunk,
          highlights: Array.isArray(chunk.highlights) ? chunk.highlights : [],
        };
        const existing = fileMap.get(fileIdentity);
        if (existing) {
          existing.chunks.push(chunkWithHighlights);
          if (!existing.embedding_model && chunk.embedding_model) {
            existing.embedding_model = chunk.embedding_model;
          }
          if (
            existing.embedding_dimensions == null &&
            typeof chunk.embedding_dimensions === "number"
          ) {
            existing.embedding_dimensions = chunk.embedding_dimensions;
          }
        } else {
          fileMap.set(fileIdentity, {
            filename: fileIdentity,
            mimetype: chunk.mimetype,
            chunks: [chunkWithHighlights],
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
          });
        }
      });

      // Literal-match gate: if no meaningful query token appears verbatim in
      // any chunk, suppress results so the no-results overlay fires instead of
      // showing a misleading "High (100%)" badge from pure KNN drift.
      // Warnings are always preserved. Not applied for wildcard queries.
      const pendingWarnings: SearchWarning[] = Array.isArray(data.warnings)
        ? data.warnings
        : [];

      if (!isWildcardQuery && !options?.disableLiteralGate) {
        const allChunksForGate = Array.from(fileMap.values()).flatMap(
          (f) => f.chunks,
        );

        const allTokens = normalizedQuery
          .toLowerCase()
          .split(/\s+/)
          .filter((t) => t.length > 0);

        const meaningfulTokens = allTokens.filter(
          (t) => !GATE_STOPWORDS.has(t),
        );

        // Fall back to all tokens when the query is entirely stopwords.
        const gateTokens =
          meaningfulTokens.length > 0 ? meaningfulTokens : allTokens;

        const hasTextMatch =
          gateTokens.length > 0 &&
          allChunksForGate.some((c) => {
            const text = (c.text ?? "").toLowerCase();
            return gateTokens.some((token) => text.includes(token));
          });

        if (!hasTextMatch) {
          return { files: [], warnings: pendingWarnings };
        }
      }

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
        const normScores = file.chunks.map((c) => normalise(c.score ?? 0));
        const fileMaxNorm = Math.max(...normScores);
        const chunkTiers: ChunkTiers = { high: 0, medium: 0, low: 0 };
        for (const norm of normScores) {
          chunkTiers[toTier(norm)]++;
        }
        return {
          filename: file.filename,
          mimetype: file.mimetype,
          chunkCount: file.chunks.length,
          maxScore: fileMaxNorm,
          relevanceTier: toTier(fileMaxNorm),
          chunkTiers,
          source_url: file.source_url || "",
          owner: file.owner || "",
          owner_name: file.owner_name || "",
          owner_email: file.owner_email || "",
          size: file.file_size || 0,
          connector_type: file.connector_type || "local",
          embedding_model: file.embedding_model,
          embedding_dimensions: file.embedding_dimensions,
          chunks: file.chunks,
          allowed_users: file.allowed_users || [],
          allowed_groups: file.allowed_groups || [],
        };
      });

      return { files, warnings: pendingWarnings };
    } catch (error) {
      console.error("Error getting files", error);
      throw error;
    }
  }

  return useQuery(
    {
      queryKey: ["search", queryData, query],
      placeholderData: (prev) => prev,
      staleTime: 0,
      queryFn: getFiles,
      retry: false,
      ...options,
    },
    queryClient,
  );
};
