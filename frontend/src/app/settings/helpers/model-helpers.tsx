import AnthropicLogo from "@/components/logo/anthropic-logo";
import IBMLogo from "@/components/logo/ibm-logo";
import OllamaLogo from "@/components/logo/ollama-logo";
import OpenAILogo from "@/components/logo/openai-logo";

export type ModelProvider = "openai" | "anthropic" | "ollama" | "watsonx";

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
          { value: "gpt-4", label: "GPT-4" },
          { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
          { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
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
          { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
          { value: "claude-opus-4-1-20250805", label: "Claude Opus 4.1" },
          { value: "claude-opus-4-20250514", label: "Claude Opus 4" },
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
          { value: "gpt-4", label: "GPT-4" },
          { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
          { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
        ],
        embedding: [
          { value: "text-embedding-ada-002", label: "text-embedding-ada-002" },
          { value: "text-embedding-3-small", label: "text-embedding-3-small" },
          { value: "text-embedding-3-large", label: "text-embedding-3-large" },
        ],
      };
  }
}
