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
  offset?: number;
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
    | "hidden"
    | "sync";
  error?: string;
  chunks?: ChunkResult[];
  allowed_users?: string[];
  allowed_groups?: string[];
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

const EMPTY_SEARCH_RESULT: SearchResult = { files: [], warnings: [] };

export { EMPTY_SEARCH_RESULT };

// Chunk page size used when paginating the wildcard listing.
// Smaller than WILDCARD_QUERY_LIMIT to avoid oversized individual requests
// while still covering corpora with many thousands of chunks per pass.
const WILDCARD_PAGE_SIZE = 1000;

/** Fire one POST /api/search and return the raw JSON. */
async function fetchSearchPage(payload: SearchPayload): Promise<{
  results: ChunkResult[];
  aggregations: Record<string, unknown>;
  warnings?: SearchWarning[];
}> {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorData = await response
      .json()
      .catch(() => ({ error: "Unknown error" }));
    throw new Error(
      errorData.error || `Search failed with status ${response.status}`,
    );
  }

  return response.json();
}

/** Merge a batch of chunks into the running file map. */
function mergeChunksIntoFileMap(
  chunks: ChunkResult[],
  fileMap: Map<
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
    }
  >,
  getFileIdentity: (chunk: ChunkResult) => string,
): void {
  for (const chunk of chunks) {
    const fileIdentity = getFileIdentity(chunk);
    const existing = fileMap.get(fileIdentity);
    if (existing) {
      existing.chunks.push(chunk);
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
    } else {
      fileMap.set(fileIdentity, {
        filename: fileIdentity,
        mimetype: chunk.mimetype,
        chunks: [chunk],
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
      });
    }
  }
}

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
  >,
) => {
  const queryClient = useQueryClient();

  // Normalize the query to match what will actually be searched
  const effectiveQuery = query || queryData?.query || "*";
  const normalizedQuery = effectiveQuery.trim();

  async function getFiles(): Promise<SearchResult> {
    try {
      const isWildcardQuery =
        effectiveQuery.trim() === "*" || effectiveQuery.trim() === "";

      if (isWildcardQuery) {
        // ── Wildcard path: paginate through ALL chunks to build a complete file list ──
        // A single request capped at WILDCARD_QUERY_LIMIT chunks misses files whose
        // chunks happen to fall past the limit boundary. Instead, fetch pages of
        // WILDCARD_PAGE_SIZE chunks, advancing the offset until the last page arrives
        // (fewer results than the page size), then deduplicate into a file list.
        const basePayload: SearchPayload = {
          query: effectiveQuery,
          limit: WILDCARD_PAGE_SIZE,
          scoreThreshold: 0, // match_all — no score threshold
        };
        if (queryData?.filters) {
          basePayload.filters =
            buildSearchPayloadFilters(queryData.filters) ?? undefined;
        }

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
          }
        >();

        let offset = 0;
        let warnings: SearchWarning[] = [];

        while (true) {
          const page = await fetchSearchPage({ ...basePayload, offset });

          if (offset === 0) {
            warnings = Array.isArray(page.warnings) ? page.warnings : [];
          }

          const chunks: ChunkResult[] = page.results ?? [];
          mergeChunksIntoFileMap(chunks, fileMap, getFileIdentity);

          // Stop when this page has fewer chunks than the page size (last page)
          if (chunks.length < WILDCARD_PAGE_SIZE) {
            break;
          }

          offset += WILDCARD_PAGE_SIZE;

          // Safety cap: never exceed WILDCARD_QUERY_LIMIT total chunks fetched.
          // This prevents runaway loops against unexpectedly huge corpora while
          // still being far above the previous single-request limit.
          if (offset >= SEARCH_CONSTANTS.WILDCARD_QUERY_LIMIT) {
            break;
          }
        }

        const files: File[] = Array.from(fileMap.values()).map((file) => ({
          filename: file.filename,
          mimetype: file.mimetype,
          chunkCount: file.chunks.length,
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
        }));

        return { files, warnings };
      }

      // ── Non-wildcard path: single semantic/keyword search, unchanged ──
      const searchLimit = queryData?.limit || 100;

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

      const data = await fetchSearchPage(searchPayload);

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
        }
      >();

      mergeChunksIntoFileMap(data.results ?? [], fileMap, getFileIdentity);

      const files: File[] = Array.from(fileMap.values()).map((file) => ({
        filename: file.filename,
        mimetype: file.mimetype,
        chunkCount: file.chunks.length,
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
      queryKey: ["search", queryData, query],
      placeholderData: (prev) => prev,
      staleTime: 0,
      queryFn: getFiles,
      retry: false, // Don't retry on errors - show them immediately
      ...options,
    },
    queryClient,
  );
};
