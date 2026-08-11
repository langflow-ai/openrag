import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";

interface ConfigValues {
  apiKey?: string;
  /** When true, clear the provider key (e.g. environment-key mode). */
  clearApiKey?: boolean;
  endpoint?: string;
  projectId?: string;
  apiVersion?: string;
  languageModel?: string;
  embeddingModel?: string;
}

function resolveApiKey(
  apiKey: string | undefined,
  clearApiKey: boolean | undefined,
  previous: string | undefined,
): string {
  if (clearApiKey) {
    return "";
  }
  // Explicit empty clears a typed key; omit (undefined) to reuse previous.
  if (apiKey !== undefined) {
    return apiKey;
  }
  return previous || "";
}

export function useUpdateSettings(
  provider: string,
  config: ConfigValues,
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>,
  isEmbedding?: boolean,
) {
  useEffect(() => {
    setSettings((prev) => {
      const updatedSettings: OnboardingVariables = {
        ...prev,
        embedding_model: config.embeddingModel || prev.embedding_model || "",
        llm_model: config.languageModel || prev.llm_model || "",
      };

      // Set provider field based on whether this is for embedding or LLM
      if (isEmbedding) {
        updatedSettings.embedding_provider = provider;
      } else {
        updatedSettings.llm_provider = provider;
      }

      // Map provider-specific API keys. undefined preserves prior credentials;
      // "" or clearApiKey clears; a non-empty string replaces.
      if (provider === "openai") {
        updatedSettings.openai_api_key = resolveApiKey(
          config.apiKey,
          config.clearApiKey,
          prev.openai_api_key,
        );
      } else if (provider === "anthropic") {
        updatedSettings.anthropic_api_key = resolveApiKey(
          config.apiKey,
          config.clearApiKey,
          prev.anthropic_api_key,
        );
      } else if (provider === "watsonx") {
        updatedSettings.watsonx_api_key = resolveApiKey(
          config.apiKey,
          config.clearApiKey,
          prev.watsonx_api_key,
        );
      } else if (provider === "azure_ai_foundry") {
        updatedSettings.azure_ai_foundry_api_key = resolveApiKey(
          config.apiKey,
          config.clearApiKey,
          prev.azure_ai_foundry_api_key,
        );
      }

      // Map provider-specific endpoints
      if (config.endpoint) {
        if (provider === "watsonx") {
          updatedSettings.watsonx_endpoint = config.endpoint;
        } else if (provider === "ollama") {
          updatedSettings.ollama_endpoint = config.endpoint;
        } else if (provider === "azure_ai_foundry") {
          updatedSettings.azure_ai_foundry_endpoint = config.endpoint;
        }
      }

      // Map project ID (WatsonX only)
      if (config.projectId && provider === "watsonx") {
        updatedSettings.watsonx_project_id = config.projectId;
      }

      // Map API version (Azure providers only)
      if (config.apiVersion) {
        if (provider === "azure_ai_foundry") {
          updatedSettings.azure_ai_foundry_api_version = config.apiVersion;
        }
      }

      return updatedSettings;
    });
  }, [
    provider,
    config.apiKey,
    config.clearApiKey,
    config.endpoint,
    config.projectId,
    config.apiVersion,
    config.languageModel,
    config.embeddingModel,
    setSettings,
    isEmbedding,
  ]);
}
