import type {
  ComponentState,
  ComponentStatus,
} from "@/app/api/queries/useConsoleStatusQuery";
import type { ProviderHealthResponse } from "@/app/api/queries/useProviderHealthQuery";

/** Map /provider/health onto the console-status component states. */
function providerHealthState(
  status: ProviderHealthResponse["status"],
): ComponentState {
  switch (status) {
    case "healthy":
      return "healthy";
    case "unhealthy":
    case "error":
      return "unhealthy";
    default:
      return "unknown";
  }
}

/** Prefer the specific llm/embedding key errors; fall back to the summary. */
function providerHealthMessage(health: ProviderHealthResponse): string {
  if (health.status === "healthy") {
    return health.message || "Providers configured and validated";
  }
  const { llm_error: llmError, embedding_error: embeddingError } = health;
  if (llmError && embeddingError) {
    return llmError === embeddingError
      ? llmError
      : `${llmError}; ${embeddingError}`;
  }
  return (
    llmError || embeddingError || health.message || "Provider validation failed"
  );
}

/** Adapt provider-health into a synthetic card so API-key failures use the
 *  same UI as backend components. */
export function providerHealthToComponent(
  health: ProviderHealthResponse,
): ComponentStatus {
  const metadata: Record<string, unknown> = {};
  const llmProvider = health.llm_provider ?? health.provider;
  if (llmProvider) metadata["LLM provider"] = llmProvider;
  if (health.embedding_provider) {
    metadata["Embedding provider"] = health.embedding_provider;
  }
  if (health.details?.llm_model) {
    metadata["LLM model"] = health.details.llm_model;
  }
  if (health.details?.embedding_model) {
    metadata["Embedding model"] = health.details.embedding_model;
  }

  return {
    name: "providers",
    display_name: "Model Providers",
    status: providerHealthState(health.status),
    required: true,
    message: providerHealthMessage(health),
    metadata,
  };
}
