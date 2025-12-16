/**
 * OpenRAG TypeScript SDK.
 *
 * A TypeScript/JavaScript client library for the OpenRAG API.
 *
 * @example
 * ```typescript
 * import { OpenRAGClient } from "openrag-sdk";
 *
 * // Using environment variables (OPENRAG_API_KEY, OPENRAG_URL)
 * const client = new OpenRAGClient();
 *
 * // Non-streaming chat
 * const response = await client.chat.create({ message: "What is RAG?" });
 * console.log(response.response);
 *
 * // Streaming chat with context manager (using Disposable)
 * using stream = await client.chat.stream({ message: "Explain RAG" });
 * for await (const text of stream.textStream) {
 *   process.stdout.write(text);
 * }
 *
 * // Search
 * const results = await client.search.query("document processing");
 *
 * // Ingest document
 * await client.documents.ingest({ filePath: "./report.pdf" });
 *
 * // Get settings
 * const settings = await client.settings.get();
 * ```
 *
 * @packageDocumentation
 */

export { OpenRAGClient } from "./client";
export { ChatClient, ChatStream } from "./chat";
export { SearchClient } from "./search";
export { DocumentsClient } from "./documents";

export {
  // Error types
  OpenRAGError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  ServerError,
  // Request/Response types
  OpenRAGClientOptions,
  ChatCreateOptions,
  SearchQueryOptions,
  SearchFilters,
  // Chat types
  ChatResponse,
  StreamEvent,
  ContentEvent,
  SourcesEvent,
  DoneEvent,
  Source,
  // Search types
  SearchResponse,
  SearchResult,
  // Document types
  IngestResponse,
  DeleteDocumentResponse,
  // Conversation types
  Conversation,
  ConversationDetail,
  ConversationListResponse,
  Message,
  // Settings types
  SettingsResponse,
  AgentSettings,
  KnowledgeSettings,
} from "./types";
