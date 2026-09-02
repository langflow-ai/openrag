/**
 * BomaRAG TypeScript SDK.
 *
 * A TypeScript/JavaScript client library for the BomaRAG API.
 *
 * @example
 * ```typescript
 * import { BomaRAGClient } from "bomarag-sdk";
 *
 * // Using environment variables (BOMARAG_API_KEY, BOMARAG_URL)
 * const client = new BomaRAGClient();
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

export { BomaRAGClient } from "./client";
export { ChatClient, ChatStream } from "./chat";
export { SearchClient } from "./search";
export { DocumentsClient } from "./documents";
export { KnowledgeFiltersClient } from "./knowledge-filters";

export {
  // Error types
  BomaRAGError,
  AuthenticationError,
  NotFoundError,
  ValidationError,
  RateLimitError,
  ServerError,
  // Request/Response types
  BomaRAGClientOptions,
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
  PrincipalLabel,
  FileRecord,
  GetAllFilesResponse,
  ListFilesResponse,
  ListFilesOptions,
  // Conversation types
  Conversation,
  ConversationDetail,
  ConversationListResponse,
  Message,
  // Settings types
  SettingsResponse,
  SettingsUpdateOptions,
  SettingsUpdateResponse,
  AgentSettings,
  KnowledgeSettings,
  // Knowledge filter types
  KnowledgeFilter,
  KnowledgeFilterQueryData,
  CreateKnowledgeFilterOptions,
  UpdateKnowledgeFilterOptions,
  CreateKnowledgeFilterResponse,
  KnowledgeFilterSearchResponse,
  GetKnowledgeFilterResponse,
  DeleteKnowledgeFilterResponse,
} from "./types";
