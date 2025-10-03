import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";

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
  status?:
    | "processing"
    | "active"
    | "unavailable"
    | "failed"
    | "hidden"
    | "sync";
  chunks?: ChunkResult[];
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
      const searchPayload: SearchPayload = {
        query: effectiveQuery,
        limit:
          queryData?.limit ||
          (effectiveQuery.trim() === "*" || effectiveQuery.trim() === ""
            ? 10000
            : 10), // Maximum allowed limit for wildcard searches
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
        }
      >();

      (data.results || []).forEach((chunk: ChunkResult) => {
        const existing = fileMap.get(chunk.filename);
        if (existing) {
          existing.chunks.push(chunk);
          existing.totalScore += chunk.score;
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
        chunks: file.chunks,
      }));

      return files;
    } catch (error) {
      console.error("Error getting files", error);
      return [];
    }
  }

  const queryResult = useQuery(
    {
      queryKey: ["search", queryData, query],
      placeholderData: (prev) => prev,
      queryFn: getFiles,
      ...options,
    },
    queryClient,
  );

  return queryResult;
};
