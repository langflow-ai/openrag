import type { CatalogModel } from "./catalog-models";

export const MODELS_PER_PROVIDER = 3;

export const PRIMARY_CAPABILITIES = [
  { key: "function_calling", label: "Tools", hint: "Can call tools" },
  { key: "vision", label: "Vision", hint: "Accepts images" },
  { key: "reasoning", label: "Reasoning", hint: "Extended thinking" },
] as const;

export const SECONDARY_CAPABILITIES = [
  {
    key: "structured_output",
    label: "Structured output",
    hint: "Supports JSON schemas",
  },
  {
    key: "prompt_caching",
    label: "Prompt caching",
    hint: "Caches shared prompt prefixes",
  },
  { key: "pdf_input", label: "PDF input", hint: "Accepts PDFs" },
  { key: "web_search", label: "Web search", hint: "Provider-side web search" },
  { key: "audio_input", label: "Audio in", hint: "Accepts audio" },
  { key: "computer_use", label: "Computer use", hint: "Can drive a screen" },
  {
    key: "parallel_tools",
    label: "Parallel tools",
    hint: "Can call tools in parallel",
  },
] as const;

export const ALL_CAPABILITIES = [
  ...PRIMARY_CAPABILITIES,
  ...SECONDARY_CAPABILITIES,
];

export type ModelCapability = (typeof ALL_CAPABILITIES)[number]["key"];

export function supports(model: CatalogModel, capability: ModelCapability) {
  return model.capabilities?.includes(capability) ?? false;
}

export function formatContext(tokens?: number): string {
  if (!tokens) return "";
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${millions % 1 === 0 ? millions : millions.toFixed(1)}M`;
  }
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
  return String(tokens);
}

export function formatPrice(perToken?: number): string {
  if (perToken == null) return "—";
  const perMillion = perToken * 1_000_000;
  if (perMillion === 0) return "Free";
  return `$${perMillion < 1 ? perMillion.toFixed(3) : perMillion.toFixed(2)}`;
}

export function formatTokens(tokens?: number): string {
  return tokens ? tokens.toLocaleString() : "—";
}
