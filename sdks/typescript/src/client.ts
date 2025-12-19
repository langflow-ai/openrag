/**
 * OpenRAG SDK client.
 */

import { ChatClient } from "./chat";
import { DocumentsClient } from "./documents";
import { SearchClient } from "./search";
import { KnowledgeFiltersClient } from "./knowledge-filters";
import {
  AuthenticationError,
  NotFoundError,
  OpenRAGError,
  OpenRAGClientOptions,
  RateLimitError,
  ServerError,
  SettingsResponse,
  SettingsUpdateOptions,
  SettingsUpdateResponse,
  ValidationError,
} from "./types";

/**
 * Get environment variable value.
 * Works in Node.js and environments with process.env.
 */
function getEnv(key: string): string | undefined {
  if (typeof globalThis.process !== "undefined" && globalThis.process.env) {
    return globalThis.process.env[key];
  }
  return undefined;
}

class SettingsClient {
  constructor(private client: OpenRAGClient) {}

  /**
   * Get current OpenRAG configuration.
   */
  async get(): Promise<SettingsResponse> {
    const response = await this.client._request("GET", "/api/v1/settings");
    const data = await response.json();
    return {
      agent: data.agent || {},
      knowledge: data.knowledge || {},
    };
  }

  /**
   * Update OpenRAG configuration.
   *
   * @param options - The settings to update.
   * @returns Success response with message.
   */
  async update(options: SettingsUpdateOptions): Promise<SettingsUpdateResponse> {
    const response = await this.client._request("POST", "/api/v1/settings", {
      body: JSON.stringify(options),
    });
    const data = await response.json();
    return {
      message: data.message || "Settings updated",
    };
  }
}

interface RequestOptions {
  body?: string | FormData;
  isMultipart?: boolean;
  stream?: boolean;
}

/**
 * OpenRAG API client.
 *
 * The client can be configured via constructor arguments or environment variables:
 * - OPENRAG_API_KEY: API key for authentication
 * - OPENRAG_URL: Base URL for the OpenRAG frontend (default: http://localhost:3000)
 *
 * @example
 * ```typescript
 * // Using environment variables
 * const client = new OpenRAGClient();
 * const response = await client.chat.create({ message: "Hello" });
 *
 * // Using explicit arguments
 * const client = new OpenRAGClient({
 *   apiKey: "orag_...",
 *   baseUrl: "https://api.example.com"
 * });
 * ```
 */
export class OpenRAGClient {
  private static readonly DEFAULT_BASE_URL = "http://localhost:3000";

  private readonly _apiKey: string;
  private readonly _baseUrl: string;
  private readonly _timeout: number;

  /** Chat client for conversations. */
  readonly chat: ChatClient;
  /** Search client for semantic search. */
  readonly search: SearchClient;
  /** Documents client for ingestion and deletion. */
  readonly documents: DocumentsClient;
  /** Settings client for configuration. */
  readonly settings: SettingsClient;
  /** Knowledge filters client for managing filters. */
  readonly knowledgeFilters: KnowledgeFiltersClient;

  constructor(options: OpenRAGClientOptions = {}) {
    // Resolve API key from argument or environment
    this._apiKey = options.apiKey || getEnv("OPENRAG_API_KEY") || "";
    if (!this._apiKey) {
      throw new AuthenticationError(
        "API key is required. Set OPENRAG_API_KEY environment variable or pass apiKey option."
      );
    }

    // Resolve base URL from argument or environment
    this._baseUrl = (
      options.baseUrl ||
      getEnv("OPENRAG_URL") ||
      OpenRAGClient.DEFAULT_BASE_URL
    ).replace(/\/$/, "");

    this._timeout = options.timeout ?? 30000;

    // Initialize sub-clients
    this.chat = new ChatClient(this);
    this.search = new SearchClient(this);
    this.documents = new DocumentsClient(this);
    this.settings = new SettingsClient(this);
    this.knowledgeFilters = new KnowledgeFiltersClient(this);
  }

  /** @internal Get request headers with authentication. */
  _getHeaders(isMultipart = false): Record<string, string> {
    const headers: Record<string, string> = {
      "X-API-Key": this._apiKey,
    };

    if (!isMultipart) {
      headers["Content-Type"] = "application/json";
    }

    return headers;
  }

  /** @internal Make an authenticated request to the API. */
  async _request(
    method: string,
    path: string,
    options: RequestOptions = {}
  ): Promise<Response> {
    const url = `${this._baseUrl}${path}`;
    const headers = this._getHeaders(options.isMultipart);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this._timeout);

    try {
      const response = await fetch(url, {
        method,
        headers,
        body: options.body ?? null,
        signal: controller.signal,
      });

      if (!options.stream) {
        this._handleError(response);
      }

      return response;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /** @internal Handle error responses. */
  _handleError(response: Response): void {
    if (response.ok) return;

    const statusCode = response.status;

    // We can't await the JSON here since this might be called in a sync context
    // So we throw with a generic message based on status code
    const errorMessages: Record<number, string> = {
      401: "Invalid or missing API key",
      403: "Access denied",
      404: "Resource not found",
      400: "Invalid request",
      429: "Rate limit exceeded",
    };

    const message = errorMessages[statusCode] || `HTTP ${statusCode}`;

    if (statusCode === 401 || statusCode === 403) {
      throw new AuthenticationError(message, statusCode);
    } else if (statusCode === 404) {
      throw new NotFoundError(message, statusCode);
    } else if (statusCode === 400) {
      throw new ValidationError(message, statusCode);
    } else if (statusCode === 429) {
      throw new RateLimitError(message, statusCode);
    } else if (statusCode >= 500) {
      throw new ServerError(message, statusCode);
    } else {
      throw new OpenRAGError(message, statusCode);
    }
  }
}
