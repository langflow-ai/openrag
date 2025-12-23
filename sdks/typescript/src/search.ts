/**
 * OpenRAG SDK search client.
 */

import type { OpenRAGClient } from "./client";
import type { SearchQueryOptions, SearchResponse } from "./types";

export class SearchClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Perform semantic search on documents.
   *
   * @param query - The search query text.
   * @param options - Optional search options.
   * @returns SearchResponse containing the search results.
   */
  async query(
    query: string,
    options?: Omit<SearchQueryOptions, "query">
  ): Promise<SearchResponse> {
    const body: Record<string, unknown> = {
      query,
      limit: options?.limit ?? 10,
      score_threshold: options?.scoreThreshold ?? 0,
    };

    if (options?.filters) {
      body["filters"] = options.filters;
    }

    if (options?.filterId) {
      body["filter_id"] = options.filterId;
    }

    const response = await this.client._request("POST", "/api/v1/search", {
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return {
      results: data.results || [],
    };
  }
}
