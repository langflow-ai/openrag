/**
 * Provider configuration for tests
 * Each provider has its models and test cases
 */

export interface ProviderConfig {
  provider: string; // Provider name as shown in UI
  language: string; // Language model name
  embedding: string; // Embedding model name
  testCase: {
    url: string;
    docName: string;
  };
  required?: boolean; // If true, test will fail if provider not configured
}

// OpenAI Configuration (Required)
export const OPENAI_CONFIG: ProviderConfig = {
  provider: "OpenAI",
  language: "gpt-5-mini",
  embedding: "text-embedding-ada-002",
  testCase: {
    url: "https://react.dev/reference/react/hooks",
    docName: "Built-in React Hooks – React",
  },
  required: true, // OpenAI is required
};

// Ollama Configuration (Optional)
export const OLLAMA_CONFIG: ProviderConfig = {
  provider: "Ollama",
  language: "qwen3:latest",
  embedding: "nomic-embed-text:latest",
  testCase: {
    url: "https://docs.python.org/3/library/functions.html",
    docName: "Built-in Functions — Python",
  },
};

// IBM watsonx.ai Configuration (Optional)
export const WATSONX_CONFIG: ProviderConfig = {
  provider: "IBM watsonx.ai",
  language: "ibm/granite-3-8b-instruct",
  embedding: "ibm/slate-125m-english-rtrvr-v2",
  testCase: {
    url: "https://kubernetes.io/docs/concepts/overview/",
    docName: "Overview | Kubernetes",
  },
};

// Anthropic Configuration (Optional)
export const ANTHROPIC_CONFIG: ProviderConfig = {
  provider: "Anthropic",
  language: "claude-3-5-sonnet-20241022",
  embedding: "text-embedding-3-large", // Anthropic doesn't have embeddings, use OpenAI
  testCase: {
    url: "https://nodejs.org/docs/latest/api/",
    docName: "Index | Node.js",
  },
};

// All provider configurations
export const PROVIDER_CONFIGS: ProviderConfig[] = [
  OPENAI_CONFIG,
  OLLAMA_CONFIG,
  WATSONX_CONFIG,
  ANTHROPIC_CONFIG,
];

/**
 * Model transition sequences by provider
 * Used for model switching tests
 */
export interface ModelTransitionConfig {
  provider: string;
  languageSequence: string[];
  embeddingSequence: string[];
}

export const MODEL_TRANSITIONS: ModelTransitionConfig[] = [
  {
    provider: "OpenAI",
    languageSequence: ["gpt-4o", "gpt-4o-mini"],
    embeddingSequence: ["text-embedding-3-small", "text-embedding-3-large"],
  },
  {
    provider: "Ollama",
    languageSequence: ["qwen3:latest"],
    embeddingSequence: ["nomic-embed-text:latest", "qwen3-embedding:latest"],
  },
  {
    provider: "IBM watsonx.ai",
    languageSequence: [
      "ibm/granite-3-8b-instruct",
      "ibm/granite-3-3-8b-instruct",
    ],
    embeddingSequence: [
      "ibm/slate-125m-english-rtrvr-v2",
      "ibm/granite-embedding-278m-multilingual",
    ],
  },
];
