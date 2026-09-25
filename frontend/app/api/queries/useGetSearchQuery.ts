import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { SEARCH_CONSTANTS } from "@/lib/constants";
import {
  buildSearchPayloadFilters,
  type FilterInput,
} from "@/lib/filter-normalization";

export interface SearchPayload {
  query: string;
  limit: number;
  scoreThreshold: number;
  filters?: FilterInput;
  resultMode?: "chunks" | "website_pages";
}

export interface ChunkResult {
  filename: string;
  mimetype: string;
  page: number;
  text: string;
  /** Keyword-match highlight fragments from OpenSearch. Each fragment is a
   *  substring of `text` with matched terms wrapped in `<mark>` tags.
   *  Empty array when no keyword match exists (pure semantic/KNN hit). */
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
  document_id?: string;
  web_source_id?: string;
  web_page_id?: string;
  web_page_depth?: number;
  canonical_url?: string;
  status?: File["status"];
  error?: string;
  chunk_count?: number;
}

export interface File {
  filename: string;
  mimetype: string;
  chunkCount?: number;
  avgScore?: number;
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
  /**
   * Skip reason forwarded from result.reason (e.g. "duplicate_content",
   * "deleted_at_source"). Only set when status === "skipped".
   */
  skip_reason?: string;
  /** Warning message for skipped rows (e.g. duplicate_content). */
  warning?: string;
  task_id?: string; // Task ID for file-level cancellation
  chunks?: ChunkResult[];
  allowed_users?: string[];
  allowed_groups?: string[];
  document_id?: string;
  web_source_id?: string;
  web_page_id?: string;
  web_page_depth?: number;
  web_child_count?: number;
}

// Non-fatal signal from the backend — e.g. an embedding provider was removed
// so some models in the corpus can't be queried semantically. Results still
// come back via keyword matching.
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
  resultMode?: "chunks" | "website_pages";
}

const EMPTY_SEARCH_RESULT: SearchResult = { files: [], warnings: [] };

export { EMPTY_SEARCH_RESULT };

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

  // Normalize the query to match what will actually be searched
  const effectiveQuery = query || queryData?.query || "*";
  const normalizedQuery = effectiveQuery.trim();

  async function getFiles(): Promise<SearchResult> {
    try {
      // For wildcard queries, use a high limit to get all files
      // Otherwise use the limit from queryData or default to 100
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
        resultMode: displayOptions.resultMode,
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
      // Group chunks by filename to create file results similar to page.tsx
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
          existing.totalScore += chunk.score;
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
        } else {
          fileMap.set(fileIdentity, {
            filename:
              displayOptions.groupBy === "document_id"
                ? chunk.filename || fileIdentity
                : fileIdentity,
            mimetype: chunk.mimetype,
            chunks: [chunkWithHighlights],
            totalScore: chunk.score,
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
            canonical_url: chunk.canonical_url,
            status: chunk.status,
            error: chunk.error,
            chunk_count: chunk.chunk_count,
          });
        }
      });

      const files: File[] = Array.from(fileMap.values()).map((file) => ({
        filename: file.filename,
        mimetype: file.mimetype,
        chunkCount: file.chunk_count ?? file.chunks.length,
        avgScore: file.totalScore / file.chunks.length,
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
        document_id: file.document_id,
        web_source_id: file.web_source_id,
        web_page_id: file.web_page_id,
        web_page_depth: file.web_page_depth,
        status: file.status,
        error: file.error,
      }));

      const warnings: SearchWarning[] = Array.isArray(data.warnings)
        ? data.warnings
        : [];

      return { files, warnings };
    } catch (error) {
      console.error("Error getting files", error);
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
      retry: false, // Don't retry on errors - show them immediately
      ...options,
    },
    queryClient,
  );
};
