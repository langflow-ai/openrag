import AnthropicLogo from "@/components/icons/anthropic-logo";
import AzureLogo from "@/components/icons/azure-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";

/**
 * A provider key as the backend names it.
 *
 * Which providers exist — and which of them this deployment shows — comes from
 * `GET /api/models/providers`, driven by `config/model_providers.yaml` and
 * OPENRAG_RUN_MODE. So this is a plain string, not a closed union: a provider
 * added to that file must render without a frontend change. The keys below are
 * only the ones OpenRAG has bespoke chrome (logo, colours, forms) for.
 */
export type ModelProvider = string;

export const KNOWN_PROVIDERS = [
  "openai",
  "anthropic",
  "ollama",
  "watsonx",
  "azure_ai",
  "azure",
  "local",
] as const;

export type KnownModelProvider = (typeof KNOWN_PROVIDERS)[number];

// Preferred auto-select order for the LLM onboarding step. Only a preference:
// providers this run mode hides are dropped, and anything the API returns that
// is not listed here is appended in API order.
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

/**
 * `preferred` first (skipping anything not in `available`), then whatever else
 * `available` holds, in the order the backend returned it.
 */
export function orderProviders(
  available: ModelProvider[],
  preferred: ModelProvider[],
): ModelProvider[] {
  const offered = new Set(available);
  const ranked = preferred.filter((provider) => offered.has(provider));
  const seen = new Set(ranked);
  return [...ranked, ...available.filter((provider) => !seen.has(provider))];
}

export interface ModelOption {
  value: string;
  label: string;
}

export interface ProviderChrome {
  /** Display name; the API's `display_name` wins over the built-in label. */
  name: string;
  logo: (props: React.SVGProps<SVGSVGElement>) => React.ReactNode;
  logoColor: string;
  logoBgColor: string;
  /** Onboarding tabs invert some marks; defaults to the card colours. */
  tabLogoColor?: string;
  tabLogoBgColor?: string;
}

function GenericProviderLogo(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <title>Model provider</title>
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  );
}

/** Logo and colours for the providers OpenRAG ships chrome for. */
const PROVIDER_CHROME: Record<string, ProviderChrome> = {
  openai: {
    name: "OpenAI",
    logo: OpenAILogo,
    logoColor: "text-black",
    logoBgColor: "bg-white",
  },
  anthropic: {
    name: "Anthropic",
    logo: AnthropicLogo,
    logoColor: "text-[#D97757]",
    logoBgColor: "bg-white",
    tabLogoColor: "text-black",
    tabLogoBgColor: "bg-[#D97757]",
  },
  ollama: {
    name: "Ollama",
    logo: OllamaLogo,
    logoColor: "text-black",
    logoBgColor: "bg-white",
  },
  watsonx: {
    name: "IBM watsonx.ai",
    logo: IBMLogo,
    logoColor: "text-white",
    logoBgColor: "bg-[#1063FE]",
  },
  azure_ai: {
    name: "Azure AI Foundry",
    logo: AzureLogo,
    logoColor: "text-white",
    logoBgColor: "bg-[#0078D4]",
  },
  // Azure OpenAI Service is a second Azure product, not a second brand: it
  // takes the same mark, and the display name is what tells the two cards
  // apart. Without a row here it fell through to the generic placeholder while
  // the model rows below already drew the Azure logo for it.
  azure: {
    name: "Azure OpenAI",
    logo: AzureLogo,
    logoColor: "text-white",
    logoBgColor: "bg-[#0078D4]",
  },
  local: {
    name: "Local",
    logo: GenericProviderLogo,
    logoColor: "text-muted-foreground",
    logoBgColor: "bg-white",
  },
};

/**
 * Chrome for `provider`. A provider the config file adds but the frontend has
 * no artwork for still renders, under the display name the API gave it.
 */
export function getProviderChrome(
  provider: ModelProvider,
  displayName?: string,
): ProviderChrome {
  const known = PROVIDER_CHROME[provider];
  if (known) {
    return displayName ? { ...known, name: displayName } : known;
  }
  return {
    name: displayName || provider,
    logo: GenericProviderLogo,
    logoColor: "text-black",
    logoBgColor: "bg-white",
  };
}

// Helper function to get model logo based on provider or model name
export function getModelLogo(modelValue: string, provider?: string) {
  // First check by provider
  if (provider === "openai") {
    return <OpenAILogo className="w-4 h-4" />;
  } else if (provider === "anthropic") {
    return <AnthropicLogo className="w-4 h-4" />;
  } else if (provider === "ollama") {
    return <OllamaLogo className="w-4 h-4" />;
  } else if (provider === "watsonx") {
    return <IBMLogo className="w-4 h-4" />;
  } else if (provider === "azure_ai" || provider === "azure") {
    return <AzureLogo className="w-4 h-4" />;
  } else if (provider === "local") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="w-4 h-4 text-muted-foreground"
      >
        <rect x="4" y="4" width="16" height="16" rx="2" />
        <rect x="9" y="9" width="6" height="6" />
        <path d="M9 1v3" />
        <path d="M15 1v3" />
        <path d="M9 20v3" />
        <path d="M15 20v3" />
        <path d="M20 9h3" />
        <path d="M20 15h3" />
        <path d="M1 9h3" />
        <path d="M1 15h3" />
      </svg>
    );
  } else if (provider) {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="w-4 h-4 text-muted-foreground"
      >
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    );
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

// Offline fallbacks when live /api/models/* returns empty.
// Include current preferred defaults AND older models that are still functional.
// Live provider lists remain the real catalog when the API is reachable.
export function getFallbackModels(provider: ModelProvider) {
  switch (provider) {
    case "openai":
      return {
        language: [
          // GPT-5.6 family (current frontier)
          { value: "gpt-5.6", label: "GPT-5.6" },
          { value: "gpt-5.6-sol", label: "GPT-5.6 Sol" },
          { value: "gpt-5.6-terra", label: "GPT-5.6 Terra" },
          { value: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
          // GPT-5.5
          { value: "gpt-5.5", label: "GPT-5.5" },
          { value: "gpt-5.5-pro", label: "GPT-5.5 Pro" },
          // GPT-5.4 and earlier (still functional)
          { value: "gpt-5.4", label: "GPT-5.4" },
          { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
          { value: "gpt-5.4-nano", label: "GPT-5.4 Nano" },
          { value: "gpt-5.4-pro", label: "GPT-5.4 Pro" },
          { value: "gpt-5.3-codex", label: "GPT-5.3 Codex" },
          { value: "gpt-5.2", label: "GPT-5.2" },
          { value: "gpt-5.1", label: "GPT-5.1" },
          { value: "gpt-5", label: "GPT-5" },
          { value: "gpt-5-mini", label: "GPT-5 Mini" },
          { value: "gpt-5-nano", label: "GPT-5 Nano" },
          { value: "gpt-4.1", label: "GPT-4.1" },
          { value: "gpt-4.1-mini", label: "GPT-4.1 Mini" },
          { value: "gpt-4o", label: "GPT-4o" },
          { value: "gpt-4o-mini", label: "GPT-4o Mini" },
          { value: "o3", label: "o3" },
          { value: "o3-pro", label: "o3 Pro" },
          { value: "o4-mini", label: "o4 Mini" },
          { value: "o4-mini-high", label: "o4 Mini High" },
        ],
        embedding: [
          { value: "text-embedding-3-large", label: "text-embedding-3-large" },
          { value: "text-embedding-3-small", label: "text-embedding-3-small" },
          { value: "text-embedding-ada-002", label: "text-embedding-ada-002" },
        ],
      };
    case "anthropic":
      return {
        language: [
          // Claude 5 family (current)
          { value: "claude-fable-5", label: "Claude Fable 5" },
          { value: "claude-opus-5", label: "Claude Opus 5" },
          { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
          // Claude 4.x (still functional)
          { value: "claude-opus-4-8", label: "Claude Opus 4.8" },
          { value: "claude-opus-4-7", label: "Claude Opus 4.7" },
          { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
          { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
          { value: "claude-opus-4-5-20251101", label: "Claude Opus 4.5" },
          { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
          { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
        ],
      };
    case "ollama":
      return {
        // Tool-calling capable recommendations only (agent requires tools)
        language: [
          { value: "gpt-oss", label: "gpt-oss" },
          { value: "mistral-nemo", label: "mistral-nemo" },
          { value: "llama3.1", label: "Llama 3.1" },
          { value: "qwen2.5", label: "Qwen 2.5" },
        ],
        embedding: [
          { value: "nomic-embed-text", label: "Nomic Embed Text" },
          { value: "mxbai-embed-large", label: "MxBai Embed Large" },
        ],
      };
    case "watsonx":
      // No stable static IDs — live list is required for watsonx.
      return { language: [], embedding: [] };
    default:
      return {
        language: [
          { value: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
          { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
          { value: "gpt-4o", label: "GPT-4o" },
          { value: "gpt-4o-mini", label: "GPT-4o Mini" },
        ],
        embedding: [
          { value: "text-embedding-3-small", label: "text-embedding-3-small" },
          { value: "text-embedding-3-large", label: "text-embedding-3-large" },
        ],
      };
  }
}
