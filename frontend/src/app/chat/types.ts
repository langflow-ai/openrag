export interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  functionCalls?: FunctionCall[];
  isStreaming?: boolean;
  source?: "langflow" | "chat";
}

export interface FunctionCall {
  name: string;
  arguments?: Record<string, unknown>;
  result?: Record<string, unknown> | ToolCallResult[];
  status: "pending" | "completed" | "error";
  argumentsString?: string;
  id?: string;
  type?: string;
}

export interface ToolCallResult {
  text_key?: string;
  data?: {
    file_path?: string;
    text?: string;
    [key: string]: unknown;
  };
  default_value?: string;
  [key: string]: unknown;
}

export interface SelectedFilters {
  data_sources: string[];
  document_types: string[];
  owners: string[];
}

export interface KnowledgeFilterData {
  id: string;
  name: string;
  description: string;
  query_data: string;
  owner: string;
  created_at: string;
  updated_at: string;
}

export interface RequestBody {
  prompt: string;
  stream?: boolean;
  previous_response_id?: string;
  filters?: SelectedFilters;
  limit?: number;
  scoreThreshold?: number;
}
