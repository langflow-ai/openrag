/** Provider marks vendored from LiteLLM's dashboard via OpenRAG-next. */
const DIRECT: Record<string, string> = {
  ai21: "ai21.svg",
  ai21_chat: "ai21.svg",
  aiohttp_openai: "openai_small.svg",
  anthropic: "anthropic.svg",
  anthropic_text: "anthropic.svg",
  azure: "microsoft_azure.svg",
  azure_ai: "microsoft_azure.svg",
  azure_text: "microsoft_azure.svg",
  baseten: "baseten.svg",
  bedrock: "bedrock.svg",
  bedrock_mantle: "bedrock.svg",
  cerebras: "cerebras.svg",
  cloudflare: "cloudflare.svg",
  codestral: "mistral.svg",
  cohere: "cohere.svg",
  cohere_chat: "cohere.svg",
  dashscope: "qwen.png",
  databricks: "databricks.svg",
  deepinfra: "deepinfra.png",
  deepseek: "deepseek.svg",
  featherless_ai: "featherless.svg",
  fireworks_ai: "fireworks.svg",
  friendliai: "friendli.svg",
  gemini: "google.svg",
  github_copilot: "github_copilot.svg",
  groq: "groq.svg",
  hyperbolic: "hyperbolic.svg",
  lambda_ai: "lambda.svg",
  meta_llama: "meta_llama.svg",
  minimax: "minimax.svg",
  mistral: "mistral.svg",
  moonshot: "moonshot.svg",
  morph: "morph.svg",
  nebius: "nebius.svg",
  novita: "novita.svg",
  oci: "oracle.svg",
  ollama: "ollama.svg",
  ollama_chat: "ollama.svg",
  oobabooga: "openai_small.svg",
  openai: "openai_small.svg",
  openai_like: "openai_small.svg",
  openrouter: "openrouter.svg",
  perplexity: "perplexity-ai.svg",
  replicate: "replicate.svg",
  sagemaker: "bedrock.svg",
  sagemaker_chat: "bedrock.svg",
  sambanova: "sambanova.svg",
  snowflake: "snowflake.svg",
  "text-completion-codestral": "mistral.svg",
  "text-completion-openai": "openai_small.svg",
  together_ai: "togetherai.svg",
  v0: "v0.svg",
  vercel_ai_gateway: "vercel.svg",
  vertex_ai: "google.svg",
  vertex_ai_beta: "google.svg",
  volcengine: "volcengine.png",
  watsonx: "watsonx.svg",
  watsonx_text: "watsonx.svg",
  xai: "xai.svg",
};

const FAMILIES: ReadonlyArray<readonly [string, string]> = [
  ["bedrock", "bedrock"],
  ["vertex_ai", "vertex_ai"],
  ["azure", "azure"],
  ["openai", "openai"],
  ["ollama", "ollama"],
  ["cohere", "cohere"],
  ["gemini", "gemini"],
  ["sagemaker", "sagemaker"],
];

export function providerLogo(provider: string): string | null {
  const key = provider.trim().toLowerCase();
  if (!key) return null;
  const direct = DIRECT[key];
  if (direct) return `/provider-logos/${direct}`;
  for (const [prefix, parent] of FAMILIES) {
    if (
      key === prefix ||
      key.startsWith(`${prefix}_`) ||
      key.startsWith(`${prefix}-`)
    ) {
      const inherited = DIRECT[parent];
      if (inherited) return `/provider-logos/${inherited}`;
    }
  }
  return null;
}

export function providerMonogram(provider: string): string {
  const parts = provider.split(/[_-]/).filter(Boolean);
  const letters =
    parts.length > 1
      ? `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`
      : provider.slice(0, 2);
  return letters.toUpperCase();
}
