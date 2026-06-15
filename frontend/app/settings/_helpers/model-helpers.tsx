import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";

export type ModelProvider = "openai" | "anthropic" | "ollama" | "watsonx";

// Full ordered list of providers for settings / cards
export const ALL_PROVIDERS: ModelProvider[] = [
  "openai",
  "ollama",
  "watsonx",
  "anthropic",
];

// Preferred auto-select order for the LLM onboarding step
export const LLM_PROVIDER_ORDER: ModelProvider[] = [
  "anthropic",
  "openai",
  "watsonx",
  "ollama",
];

// Preferred auto-select order for the embedding onboarding step
export const EMBEDDING_PROVIDER_ORDER: ModelProvider[] = [
  "openai",
  "watsonx",
  "ollama",
];

// Providers unavailable in cloud (IBM) deployments
export const CLOUD_EXCLUDED_PROVIDERS: ModelProvider[] = ["ollama"];

export interface ModelOption {
  value: string;
  label: string;
}

// Helper function to get model logo based on provider or model name
export function getModelLogo(modelValue: string, provider?: ModelProvider) {
  // First check by provider
  if (provider === "openai") {
    return <OpenAILogo className="w-4 h-4" />;
  } else if (provider === "anthropic") {
    return <AnthropicLogo className="w-4 h-4" />;
  } else if (provider === "ollama") {
    return <OllamaLogo className="w-4 h-4" />;
  } else if (provider === "watsonx") {
    return <IBMLogo className="w-4 h-4" />;
  }

  // Fallback to model name analysis
  if (modelValue.includes("gpt") || modelValue.includes("text-embedding")) {
    return <OpenAILogo className="w-4 h-4" />;
  } else if (modelValue.includes("llama") || modelValue.includes("ollama")) {
    return <OllamaLogo className="w-4 h-4" />;
  } else if (
    modelValue.includes("granite") ||
    modelValue.includes("slate") ||
    modelValue.includes("ibm")
  ) {
    return <IBMLogo className="w-4 h-4" />;
  }

  return <OpenAILogo className="w-4 h-4" />; // Default to OpenAI logo
}

// Helper function to get fallback models by provider
export function getFallbackModels(provider: ModelProvider) {
  switch (provider) {
    case "openai":
      return {
        language: [
          { value: "gpt-5.4", label: "GPT-5.4" },
          { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
          { value: "gpt-5.4-pro", label: "GPT-5.4 Pro" },
          { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
          { value: "gpt-5.2", label: "GPT-5.2" },
          { value: "gpt-5.1", label: "GPT-5.1" },
          { value: "gpt-5", label: "GPT-5" },
          { value: "gpt-5-mini", label: "GPT-5 Mini" },
          { value: "gpt-5-nano", label: "GPT-5 Nano" },
          { value: "gpt-4o-mini", label: "GPT-4o Mini" },
          { value: "gpt-4o", label: "GPT-4o" },
          { value: "gpt-4.1", label: "GPT-4.1" },
          { value: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
          { value: "o3", label: "o3" },
          { value: "o3-pro", label: "o3 Pro" },
          { value: "o4-mini-high", label: "o4 Mini High" },
        ],
        embedding: [
          { value: "text-embedding-ada-002", label: "text-embedding-ada-002" },
          { value: "text-embedding-3-small", label: "text-embedding-3-small" },
          { value: "text-embedding-3-large", label: "text-embedding-3-large" },
        ],
      };
    case "anthropic":
      return {
        language: [
          { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
          { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
          { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
        ],
      };
    case "ollama":
      return {
        language: [
          { value: "llama2", label: "Llama 2" },
          { value: "llama2:13b", label: "Llama 2 13B" },
          { value: "codellama", label: "Code Llama" },
        ],
        embedding: [
          { value: "mxbai-embed-large", label: "MxBai Embed Large" },
          { value: "nomic-embed-text", label: "Nomic Embed Text" },
        ],
      };
    case "watsonx":
      return {
        language: [
          {
            value: "meta-llama/llama-3-1-70b-instruct",
            label: "Llama 3.1 70B Instruct",
          },
          { value: "ibm/granite-13b-chat-v2", label: "Granite 13B Chat v2" },
        ],
        embedding: [
          {
            value: "ibm/slate-125m-english-rtrvr",
            label: "Slate 125M English Retriever",
          },
        ],
      };
    default:
      return {
        language: [
          { value: "gpt-5.4", label: "GPT-5.4" },
          { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
          { value: "gpt-5.4-pro", label: "GPT-5.4 Pro" },
          { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
          { value: "gpt-5.2", label: "GPT-5.2" },
          { value: "gpt-5.1", label: "GPT-5.1" },
          { value: "gpt-5", label: "GPT-5" },
          { value: "gpt-5-mini", label: "GPT-5 Mini" },
          { value: "gpt-5-nano", label: "GPT-5 Nano" },
          { value: "gpt-4o-mini", label: "GPT-4o Mini" },
          { value: "gpt-4o", label: "GPT-4o" },
          { value: "gpt-4.1", label: "GPT-4.1" },
          { value: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
          { value: "o3", label: "o3" },
          { value: "o3-pro", label: "o3 Pro" },
          { value: "o4-mini-high", label: "o4 Mini High" },
        ],
        embedding: [
          { value: "text-embedding-ada-002", label: "text-embedding-ada-002" },
          { value: "text-embedding-3-small", label: "text-embedding-3-small" },
          { value: "text-embedding-3-large", label: "text-embedding-3-large" },
        ],
      };
  }
}
