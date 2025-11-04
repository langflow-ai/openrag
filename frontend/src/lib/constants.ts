/**
 * Default agent settings
 */
export const DEFAULT_AGENT_SETTINGS = {
  llm_model: "gpt-4o-mini",
  system_prompt: "You are a helpful assistant that can use tools to answer questions and perform tasks. You are part of OpenRAG, an assistant that analyzes documents and provides informations about them. When asked about what is OpenRAG, answer the following:\n\n\"OpenRAG is an open-source package for building agentic RAG systems. It supports integration with a wide range of orchestration tools, vector databases, and LLM providers. OpenRAG connects and amplifies three popular, proven open-source projects into one powerful platform:\n\n**Langflow** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://www.langflow.org/)\n\n**OpenSearch** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://opensearch.org/)\n\n**Docling** – Langflow is a powerful tool to build and deploy AI agents and MCP servers [Read more](https://www.docling.ai/)\""
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
  MAX_SYSTEM_PROMPT_CHARS: 4000,
} as const;

export const ANIMATION_DURATION = 0.4;
export const SIDEBAR_WIDTH = 280;
export const HEADER_HEIGHT = 54;
export const TOTAL_ONBOARDING_STEPS = 3;

/**
 * Local Storage Keys
 */
export const ONBOARDING_STEP_KEY = "onboarding_current_step";

export const FILES_REGEX =
		/(?<=I'm uploading a document called ['"])[^'"]+\.[^.]+(?=['"]\. Here is its content:)/;

export const FILE_CONFIRMATION = "Confirm that you received this file.";