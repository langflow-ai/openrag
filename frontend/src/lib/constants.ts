/**
 * Default agent settings
 */
export const DEFAULT_AGENT_SETTINGS = {
  llm_model: "gpt-4o-mini",
  system_prompt: "You are a helpful assistant that can use tools to answer questions and perform tasks."
} as const;

/**
 * Default knowledge/ingest settings
 */
export const DEFAULT_KNOWLEDGE_SETTINGS = {
  chunk_size: 1000,
  chunk_overlap: 200,
  table_structure: true,
  ocr: false,
  picture_descriptions: false
} as const;

/**
 * UI Constants
 */
export const UI_CONSTANTS = {
  MAX_SYSTEM_PROMPT_CHARS: 2000,
} as const;

export const ANIMATION_DURATION = 0.4;
export const SIDEBAR_WIDTH = 280;
export const HEADER_HEIGHT = 54;
export const TOTAL_ONBOARDING_STEPS = 4;

/**
 * Local Storage Keys
 */
export const ONBOARDING_STEP_KEY = "onboarding_current_step";