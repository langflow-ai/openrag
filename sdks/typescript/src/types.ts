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

/** A single raw OpenSearch hit: `_source` has had embedding vectors stripped. */
export interface RawSearchHit {
  _id: string;
  _index?: string;
  _score?: number | null;
  _source: Record<string, unknown>;
}

/**
 * Response from a raw OpenSearch DSL search request.
 * `hits` is the OpenSearch response's raw `hits` object.
 */
export interface RawSearchResponse {
  took?: number;
  timed_out?: boolean;
  hits: {
    total?: { value: number; relation: string } | number;
    max_score?: number | null;
    hits: RawSearchHit[];
  };
  aggregations?: Record<string, unknown>;
}

// Document types
export interface IngestResponse {
  task_id: string;
  status?: string | null;  // Optional - we poll for actual status
  filename?: string | null;
}

export interface IngestTaskStatus {
  task_id: string;
  status: string; // "pending", "running", "completed", "failed"
  total_files: number;
  processed_files: number;
  successful_files: number;
  failed_files: number;
  files: Record<string, unknown>;
}

export interface DeleteDocumentResponse {
  success: boolean;
  deleted_chunks: number;
  filename?: string | null;
  message?: string | null;
  error?: string | null;
  // Populated when deleting by filter_id — one entry per resolved data_source.
  filenames?: string[] | null;
  filter_id?: string | null;
  per_file?: Array<Record<string, unknown>> | null;
}

export interface DeleteDocumentOptions {
  filename?: string;
  filterId?: string;
}

/** A principal label entry in a file's ACL (connector-ingested files only). */
export interface PrincipalLabel {
  principal: string;
  kind: string;
  provider: string;
  display_name?: string;
  email?: string;
  external_id?: string;
}

// File structure type
export interface FileRecord {
  filename: string;
  document_id: string;
  mimetype: string;
  file_size: number;
  source_url: string;
  owner: string;
  owner_name: string;
  owner_email: string;
  connector_type: string;
  embedding_model: string;
  embedding_dimensions: number | null;
  indexed_time: string;
  chunk_count: number;
  allowed_users: string[];
  allowed_groups: string[];
  allowed_principal_labels: PrincipalLabel[];
}

//Response from the list-files endpoint
export interface ListFilesResponse {
  files: FileRecord[];
  total: number;
  is_approximate: boolean;
  page: number;
  page_size: number;
  after_key: Record<string, unknown> | null;
}

/** Options for listing files. */
export interface ListFilesOptions {
  /** Page number (display only; use after_key for cursor navigation). Default: 1. */
  page?: number;
  /** Files per page (1–500). Default: 25. */
  page_size?: number;
  /** Sort field: filename | file_size | mimetype | indexed_time | connector_type | chunk_count | owner. */
  sort_by?: string;
  /** Sort direction. Default: "asc". */
  sort_order?: "asc" | "desc";
  /** Filter by connector type. */
  connector_type?: string;
  /** Filter by MIME type. */
  mimetype?: string;
  /** Filter by owner user ID. */
  owner?: string;
  /** Substring/prefix filename search. */
  search?: string;
  /** JSON-encoded composite cursor from a previous response's after_key. */
  after_key?: string;
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
  system_prompt?: string | null;
}

export interface KnowledgeSettings {
  embedding_provider?: string | null;
  embedding_model?: string | null;
  chunk_size?: number | null;
  chunk_overlap?: number | null;
  table_structure?: boolean | null;
  ocr?: boolean | null;
  picture_descriptions?: boolean | null;
}

export interface SettingsResponse {
  agent: AgentSettings;
  knowledge: KnowledgeSettings;
}

/** Options for updating settings. */
export interface SettingsUpdateOptions {
  /** LLM model name. */
  llm_model?: string;
  /** LLM provider (openai, anthropic, watsonx, ollama). */
  llm_provider?: string;
  /** System prompt for the agent. */
  system_prompt?: string;
  /** Embedding model name. */
  embedding_model?: string;
  /** Embedding provider (openai, watsonx, ollama). */
  embedding_provider?: string;
  /** Chunk size for document splitting. */
  chunk_size?: number;
  /** Chunk overlap for document splitting. */
  chunk_overlap?: number;
  /** Enable table structure parsing. */
  table_structure?: boolean;
  /** Enable OCR for text extraction. */
  ocr?: boolean;
  /** Enable picture descriptions. */
  picture_descriptions?: boolean;
}

/** Response from settings update. */
export interface SettingsUpdateResponse {
  message: string;
}

// Knowledge filter types
/** Query configuration stored in a knowledge filter. */
export interface KnowledgeFilterQueryData {
  /** Semantic search query text. */
  query?: string;
  /** Filter criteria for documents. */
  filters?: {
    data_sources?: string[];
    document_types?: string[];
    owners?: string[];
    connector_types?: string[];
  };
  /** Maximum number of results. */
  limit?: number;
  /** Minimum relevance score threshold. */
  scoreThreshold?: number;
  /** UI color for the filter. */
  color?: string;
  /** UI icon for the filter. */
  icon?: string;
}

/** A knowledge filter definition. */
export interface KnowledgeFilter {
  id: string;
  name: string;
  description?: string;
  queryData: KnowledgeFilterQueryData;
  owner?: string;
  createdAt?: string;
  updatedAt?: string;
}

/** Options for creating a knowledge filter. */
export interface CreateKnowledgeFilterOptions {
  /** Filter name (required). */
  name: string;
  /** Filter description. */
  description?: string;
  /** Query configuration for the filter. */
  queryData: KnowledgeFilterQueryData;
}

/** Options for updating a knowledge filter. */
export interface UpdateKnowledgeFilterOptions {
  /** New filter name. */
  name?: string;
  /** New filter description. */
  description?: string;
  /** New query configuration. */
  queryData?: KnowledgeFilterQueryData;
}

/** Response from creating a knowledge filter. */
export interface CreateKnowledgeFilterResponse {
  success: boolean;
  id?: string;
  error?: string;
}

/** Response from searching knowledge filters. */
export interface KnowledgeFilterSearchResponse {
  success: boolean;
  filters: KnowledgeFilter[];
}

/** Response from getting a knowledge filter. */
export interface GetKnowledgeFilterResponse {
  success: boolean;
  filter?: KnowledgeFilter;
  error?: string;
}

/** Response from deleting a knowledge filter. */
export interface DeleteKnowledgeFilterResponse {
  success: boolean;
  error?: string;
}

// Client options
export interface OpenRAGClientOptions {
  /** API key for authentication. Falls back to OPENRAG_API_KEY env var.
   *  Optional when using IBM auth — pass credentials via extraHeaders instead. */
  apiKey?: string;
  /** Additional headers forwarded on every request. Used in IBM auth mode
   *  to pass X-Username and X-Api-Key from the user's MCP config. */
  extraHeaders?: Record<string, string>;
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
  /** Knowledge filter ID to apply to the chat. */
  filterId?: string;
}

export interface SearchQueryOptions {
  query: string;
  filters?: SearchFilters;
  limit?: number;
  scoreThreshold?: number;
  /** Knowledge filter ID to apply to the search. */
  filterId?: string;
  /**
   * OpenSearch fuzziness for the keyword-match clause. See the
   * openrag_search MCP tool description for accepted values.
   * Defaults to "AUTO:7,10".
   */
  fuzziness?: string;
}

export interface RawSearchQueryOptions {
  /** OpenSearch query DSL object, or a JSON/plain-text string (falls back to a keyword match). */
  query: Record<string, unknown> | string;
  filters?: SearchFilters;
  /** Result size cap, applied unless `query` already sets "size". */
  limit?: number;
  /** Minimum `_score`, applied unless `query` already sets "min_score". */
  scoreThreshold?: number;
  /** Knowledge filter ID to apply to the search. */
  filterId?: string;
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
