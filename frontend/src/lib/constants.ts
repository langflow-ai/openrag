/**
 * Default agent settings
 */
export const DEFAULT_AGENT_SETTINGS = {
  llm_model: "gpt-4o-mini",
  system_prompt:
    "You are a helpful assistant that can use tools to answer questions and perform tasks.",
} as const;

/**
 * Default knowledge/ingest settings
 */
export const DEFAULT_KNOWLEDGE_SETTINGS = {
  chunk_size: 1000,
  chunk_overlap: 200,
  processing_mode: "standard",
  table_structure: false,
  ocr: false,
  picture_descriptions: false,
  embedding_model: "text-embedding-3-small",
} as const;

/**
 * UI Constants
 */
export const UI_CONSTANTS = {
  MAX_SYSTEM_PROMPT_CHARS: 2000,
} as const;
