/**
 * OpenRAG SDK models client.
 */

import type { OpenRAGClient } from "./client";
import type { ModelsResponse } from "./types";

export class ModelsClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * List available language and embedding models for a provider.
   *
   * @param provider - One of openai, anthropic, ollama, watsonx.
   */
  async list(provider: string): Promise<ModelsResponse> {
    const response = await this.client._request("GET", `/api/v1/models/${provider}`);
    const data = await response.json();
    return {
      language_models: data.language_models ?? [],
      embedding_models: data.embedding_models ?? [],
    };
  }
}
