/**
 * OpenRAG SDK types.
 */

// Chat types
export interface Source {
  filename: string;
  text: string;
  score: number;
  page?: number | null;
  mimetype?: string | null;
}

export interface ChatResponse {
  response: string;
  chatId?: string | null;
  sources: Source[];
}

export type StreamEventType = "content" | "sources" | "done";

export interface ContentEvent {
  type: "content";
  delta: string;
}

export interface SourcesEvent {
  type: "sources";
  sources: Source[];
}

export interface DoneEvent {
  type: "done";
  chatId?: string | null;
}

export type StreamEvent = ContentEvent | SourcesEvent | DoneEvent;

// Search types
export interface SearchResult {
  filename: string;
  text: string;
  score: number;
  page?: number | null;
  mimetype?: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
}

export interface SearchFilters {
  data_sources?: string[];
  document_types?: string[];
}

// Document types
export interface IngestResponse {
  success: boolean;
  document_id?: string | null;
  filename?: string | null;
  chunks: number;
}

export interface DeleteDocumentResponse {
  success: boolean;
  deleted_chunks: number;
}

// Chat history types
export interface Message {
  role: string;
  content: string;
  timestamp?: string | null;
}

export interface Conversation {
  chatId: string;
  title: string;
  createdAt?: string | null;
  lastActivity?: string | null;
  messageCount: number;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface ConversationListResponse {
  conversations: Conversation[];
}

// Settings types
export interface AgentSettings {
  llm_provider?: string | null;
  llm_model?: string | null;
}

export interface KnowledgeSettings {
  embedding_provider?: string | null;
  embedding_model?: string | null;
  chunk_size?: number | null;
  chunk_overlap?: number | null;
}

export interface SettingsResponse {
  agent: AgentSettings;
  knowledge: KnowledgeSettings;
}

// Client options
export interface OpenRAGClientOptions {
  /** API key for authentication. Falls back to OPENRAG_API_KEY env var. */
  apiKey?: string;
  /** Base URL for the API. Falls back to OPENRAG_URL env var. */
  baseUrl?: string;
  /** Request timeout in milliseconds (default 30000). */
  timeout?: number;
}

// Request types
export interface ChatCreateOptions {
  message: string;
  stream?: boolean;
  chatId?: string;
  filters?: SearchFilters;
  limit?: number;
  scoreThreshold?: number;
}

export interface SearchQueryOptions {
  query: string;
  filters?: SearchFilters;
  limit?: number;
  scoreThreshold?: number;
}

// Error types
export class OpenRAGError extends Error {
  constructor(
    message: string,
    public statusCode?: number
  ) {
    super(message);
    this.name = "OpenRAGError";
  }
}

export class AuthenticationError extends OpenRAGError {
  constructor(message: string, statusCode?: number) {
    super(message, statusCode);
    this.name = "AuthenticationError";
  }
}

export class NotFoundError extends OpenRAGError {
  constructor(message: string, statusCode?: number) {
    super(message, statusCode);
    this.name = "NotFoundError";
  }
}

export class ValidationError extends OpenRAGError {
  constructor(message: string, statusCode?: number) {
    super(message, statusCode);
    this.name = "ValidationError";
  }
}

export class RateLimitError extends OpenRAGError {
  constructor(message: string, statusCode?: number) {
    super(message, statusCode);
    this.name = "RateLimitError";
  }
}

export class ServerError extends OpenRAGError {
  constructor(message: string, statusCode?: number) {
    super(message, statusCode);
    this.name = "ServerError";
  }
}
