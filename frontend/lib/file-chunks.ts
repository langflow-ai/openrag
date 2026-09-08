import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { SEARCH_CONSTANTS } from "@/lib/constants";

/** Query data that loads all chunks for one filename (OpenSearch data_sources). */
export function fileScopedSearchQueryData(filename: string): ParsedQueryData {
  return {
    query: "*",
    filters: {
      data_sources: [filename],
      document_types: [],
      owners: [],
      connector_types: [],
    },
    limit: SEARCH_CONSTANTS.WILDCARD_QUERY_LIMIT,
    scoreThreshold: 0,
    color: "zinc",
    icon: "folder",
  };
}
