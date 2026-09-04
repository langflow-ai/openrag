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
  language: "ibm/granite-4-h-small",
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

// Azure OpenAI Configuration
export const AZURE_CONFIG: ProviderConfig = {
  provider: "Azure OpenAI",
  language: process.env.LLM_MODEL || "gpt-4.1",
  embedding: process.env.EMBEDDING_MODEL || "text-embedding-3-small",
  testCase: {
    url: "https://react.dev/reference/react/hooks",
    docName: "Built-in React Hooks – React",
  },
  required: true,
};

function resolveActiveProvider(): ProviderConfig {
  const provider = (process.env.LLM_PROVIDER || "").trim().toLowerCase();
  const llmModel = process.env.LLM_MODEL;
  const embeddingModel = process.env.EMBEDDING_MODEL;

  if (provider === "azure" || provider === "azure_ai") {
    return {
      provider: "Azure OpenAI",
      language: llmModel || "gpt-4.1",
      embedding: embeddingModel || "text-embedding-3-small",
      testCase: {
        url: "https://react.dev/reference/react/hooks",
        docName: "Built-in React Hooks – React",
      },
      required: true,
    };
  }

  if (provider === "watsonx" || provider === "ibm") {
    return {
      ...WATSONX_CONFIG,
      language: llmModel || WATSONX_CONFIG.language,
      embedding: embeddingModel || WATSONX_CONFIG.embedding,
    };
  }

  if (provider === "ollama") {
    return {
      ...OLLAMA_CONFIG,
      language: llmModel || OLLAMA_CONFIG.language,
      embedding: embeddingModel || OLLAMA_CONFIG.embedding,
    };
  }

  if (provider === "anthropic") {
    return {
      ...ANTHROPIC_CONFIG,
      language: llmModel || ANTHROPIC_CONFIG.language,
      embedding: embeddingModel || ANTHROPIC_CONFIG.embedding,
    };
  }

  if (provider === "openai") {
    return {
      provider: "OpenAI",
      language: llmModel || "gpt-5-mini",
      embedding: embeddingModel || "text-embedding-ada-002",
      testCase: {
        url: "https://react.dev/reference/react/hooks",
        docName: "Built-in React Hooks – React",
      },
      required: true,
    };
  }

  // Fallback: If Azure keys are set, use Azure OpenAI; otherwise OpenAI
  if (process.env.AZURE_OPENAI_API_KEY || process.env.AZURE_API_KEY) {
    return AZURE_CONFIG;
  }

  return {
    provider: "OpenAI",
    language: llmModel || "gpt-5-mini",
    embedding: embeddingModel || "text-embedding-ada-002",
    testCase: {
      url: "https://react.dev/reference/react/hooks",
      docName: "Built-in React Hooks – React",
    },
    required: true,
  };
}

// Active provider determined generically by LLM_PROVIDER or configured credentials
export const ACTIVE_PROVIDER_CONFIG: ProviderConfig = resolveActiveProvider();
export const MAIN_PROVIDER_CONFIG: ProviderConfig = ACTIVE_PROVIDER_CONFIG;
export const OPENAI_CONFIG: ProviderConfig = ACTIVE_PROVIDER_CONFIG;

// All provider configurations
export const PROVIDER_CONFIGS: ProviderConfig[] = [
  AZURE_CONFIG,
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
    languageSequence: ["ibm/granite-4-h-small", "ibm/granite-3-3-8b-instruct"],
    embeddingSequence: [
      "ibm/slate-125m-english-rtrvr-v2",
      "ibm/granite-embedding-278m-multilingual",
    ],
  },
];
