/**
 * OpenRAG SDK search client.
 */

import type { OpenRAGClient } from "./client";
import type {
  RawSearchQueryOptions,
  RawSearchResponse,
  SearchQueryOptions,
  SearchResponse,
} from "./types";

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
      fuzziness: options?.fuzziness ?? "AUTO:4,7",
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

  /**
   * Execute a raw OpenSearch DSL query against the knowledge base.
   *
   * Unlike `query()`, which runs OpenRAG's hybrid semantic+keyword search,
   * this passes `query` through as OpenSearch Query DSL (bool queries,
   * aggregations, sort, etc.) for advanced use cases. Still enforces the
   * caller's document-level ACLs and strips embedding vectors from results.
   *
   * @param query - OpenSearch query DSL object (e.g. `{ query: { match_all: {} } }`),
   *   or a plain-text string (falls back to a keyword match).
   * @param options - Optional filters and paging.
   * @returns RawSearchResponse wrapping the OpenSearch response.
   */
  async rawQuery(
    query: RawSearchQueryOptions["query"],
    options?: Omit<RawSearchQueryOptions, "query">
  ): Promise<RawSearchResponse> {
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

    const response = await this.client._request("POST", "/api/v1/search/raw", {
      body: JSON.stringify(body),
    });

    return (await response.json()) as RawSearchResponse;
  }
}
