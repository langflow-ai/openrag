import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { SEARCH_CONSTANTS } from "@/lib/constants";

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
  score: number;
  source_url?: string;
  owner?: string;
  owner_name?: string;
  owner_email?: string;
  file_size?: number;
  connector_type?: string;
  embedding_model?: string;
  embedding_dimensions?: number;
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

export const useGetSearchQuery = (
  query: string,
  queryData?: ParsedQueryData | null,
  options?: Omit<UseQueryOptions, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  // Normalize the query to match what will actually be searched
  const effectiveQuery = query || queryData?.query || "*";

  async function getFiles(): Promise<File[]> {
    try {
      // For wildcard queries, use a high limit to get all files
      // Otherwise use the limit from queryData or default to 100
      const isWildcardQuery = effectiveQuery.trim() === "*" || effectiveQuery.trim() === "";
      const searchLimit = isWildcardQuery
        ? SEARCH_CONSTANTS.WILDCARD_QUERY_LIMIT
        : (queryData?.limit || 100);

      const searchPayload: SearchPayload = {
        query: effectiveQuery,
        limit: searchLimit,
        scoreThreshold: queryData?.scoreThreshold || 0,
      };
      if (queryData?.filters) {
        const filters = queryData.filters;

        // Only include filters if they're not wildcards (not "*")
        const hasSpecificFilters =
          !filters.data_sources.includes("*") ||
          !filters.document_types.includes("*") ||
          !filters.owners.includes("*") ||
          (filters.connector_types && !filters.connector_types.includes("*"));

        if (hasSpecificFilters) {
          const processedFilters: SearchPayload["filters"] = {};

          // Only add filter arrays that don't contain wildcards
          if (!filters.data_sources.includes("*")) {
            processedFilters.data_sources = filters.data_sources;
          }
          if (!filters.document_types.includes("*")) {
            processedFilters.document_types = filters.document_types;
          }
          if (!filters.owners.includes("*")) {
            processedFilters.owners = filters.owners;
          }
          if (
            filters.connector_types &&
            !filters.connector_types.includes("*")
          ) {
            processedFilters.connector_types = filters.connector_types;
          }

          // Only add filters object if it has any actual filters
          if (Object.keys(processedFilters).length > 0) {
            searchPayload.filters = processedFilters;
          }
        }
      }

      const response = await fetch(`/api/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(searchPayload),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: "Unknown error" }));
        throw new Error(errorData.error || `Search failed with status ${response.status}`);
      }

      const data = await response.json();
      // #region agent log
      const firstChunk = (data.results || [])[0] as ChunkResult | undefined;
      if (firstChunk) {
        const au = firstChunk.allowed_users;
        const ag = firstChunk.allowed_groups;
        fetch("http://127.0.0.1:7242/ingest/0459c69b-01d9-4ed6-bcff-99a7ce0d82ee", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            hypothesisId: "H5",
            location: "useGetSearchQuery.ts:firstChunk",
            message: "API first chunk ACL",
            data: {
              filename: firstChunk.filename,
              hasOwner: Boolean(firstChunk.owner),
              allowed_users_len: Array.isArray(au) ? au.length : 0,
              allowed_groups_len: Array.isArray(ag) ? ag.length : 0,
            },
            timestamp: Date.now(),
          }),
        }).catch(() => {});
      }
      // #endregion
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
        }
      >();

      (data.results || []).forEach((chunk: ChunkResult) => {
        const existing = fileMap.get(chunk.filename);
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
          fileMap.set(chunk.filename, {
            filename: chunk.filename,
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
      });

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

      // #region agent log
      const firstFile = files[0];
      if (firstFile) {
        fetch("http://127.0.0.1:7242/ingest/0459c69b-01d9-4ed6-bcff-99a7ce0d82ee", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            hypothesisId: "H2",
            location: "useGetSearchQuery.ts:firstFile",
            message: "aggregated file ACL",
            data: {
              filename: firstFile.filename,
              owner: firstFile.owner || null,
              allowed_users_len: (firstFile.allowed_users || []).length,
              allowed_groups_len: (firstFile.allowed_groups || []).length,
            },
            timestamp: Date.now(),
          }),
        }).catch(() => {});
      }
      // #endregion

      return files;
    } catch (error) {
      console.error("Error getting files", error);
      // Re-throw the error so React Query can handle it and trigger onError callbacks
      throw error;
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["search", queryData, query],
      placeholderData: (prev) => prev,
      queryFn: getFiles,
      retry: false, // Don't retry on errors - show them immediately
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
