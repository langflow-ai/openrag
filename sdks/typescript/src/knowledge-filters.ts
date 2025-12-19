/**
 * OpenRAG SDK knowledge filters client.
 */

import type { OpenRAGClient } from "./client";
import type {
  CreateKnowledgeFilterOptions,
  CreateKnowledgeFilterResponse,
  DeleteKnowledgeFilterResponse,
  GetKnowledgeFilterResponse,
  KnowledgeFilter,
  KnowledgeFilterSearchResponse,
  UpdateKnowledgeFilterOptions,
} from "./types";

export class KnowledgeFiltersClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Create a new knowledge filter.
   *
   * @param options - The filter options including name and queryData.
   * @returns The created filter response with ID.
   */
  async create(
    options: CreateKnowledgeFilterOptions
  ): Promise<CreateKnowledgeFilterResponse> {
    const body = {
      name: options.name,
      description: options.description ?? "",
      queryData: JSON.stringify(options.queryData),
    };

    const response = await this.client._request("POST", "/api/v1/knowledge-filters", {
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return {
      success: data.success ?? false,
      id: data.id,
      error: data.error,
    };
  }

  /**
   * Search for knowledge filters by name, description, or query content.
   *
   * @param query - Optional search query text.
   * @param limit - Maximum number of results (default 20).
   * @returns List of matching knowledge filters.
   */
  async search(query?: string, limit?: number): Promise<KnowledgeFilter[]> {
    const body = {
      query: query ?? "",
      limit: limit ?? 20,
    };

    const response = await this.client._request(
      "POST",
      "/api/v1/knowledge-filters/search",
      {
        body: JSON.stringify(body),
      }
    );

    const data = (await response.json()) as KnowledgeFilterSearchResponse;
    if (!data.success || !data.filters) {
      return [];
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return data.filters.map((f: any) => this._parseFilter(f));
  }

  /**
   * Get a specific knowledge filter by ID.
   *
   * @param filterId - The ID of the filter to retrieve.
   * @returns The knowledge filter or null if not found.
   */
  async get(filterId: string): Promise<KnowledgeFilter | null> {
    try {
      const response = await this.client._request(
        "GET",
        `/api/v1/knowledge-filters/${filterId}`
      );

      const data = (await response.json()) as GetKnowledgeFilterResponse;
      if (!data.success || !data.filter) {
        return null;
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return this._parseFilter(data.filter as any);
    } catch {
      // Filter not found or other error
      return null;
    }
  }

  /**
   * Update an existing knowledge filter.
   *
   * @param filterId - The ID of the filter to update.
   * @param options - The fields to update.
   * @returns Success status.
   */
  async update(
    filterId: string,
    options: UpdateKnowledgeFilterOptions
  ): Promise<boolean> {
    const body: Record<string, unknown> = {};

    if (options.name !== undefined) {
      body["name"] = options.name;
    }
    if (options.description !== undefined) {
      body["description"] = options.description;
    }
    if (options.queryData !== undefined) {
      body["queryData"] = JSON.stringify(options.queryData);
    }

    const response = await this.client._request(
      "PUT",
      `/api/v1/knowledge-filters/${filterId}`,
      {
        body: JSON.stringify(body),
      }
    );

    const data = await response.json();
    return data.success ?? false;
  }

  /**
   * Delete a knowledge filter.
   *
   * @param filterId - The ID of the filter to delete.
   * @returns Success status.
   */
  async delete(filterId: string): Promise<boolean> {
    const response = await this.client._request(
      "DELETE",
      `/api/v1/knowledge-filters/${filterId}`
    );

    const data = (await response.json()) as DeleteKnowledgeFilterResponse;
    return data.success ?? false;
  }

  /**
   * Parse a filter from API response, handling JSON-stringified queryData.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private _parseFilter(filter: any): KnowledgeFilter {
    let queryData = filter["query_data"] ?? filter["queryData"];
    if (typeof queryData === "string") {
      try {
        queryData = JSON.parse(queryData);
      } catch {
        queryData = {};
      }
    }

    return {
      id: filter["id"] as string,
      name: filter["name"] as string,
      description: filter["description"],
      queryData: queryData as KnowledgeFilter["queryData"],
      owner: filter["owner"],
      createdAt: filter["created_at"] ?? filter["createdAt"],
      updatedAt: filter["updated_at"] ?? filter["updatedAt"],
    };
  }
}
