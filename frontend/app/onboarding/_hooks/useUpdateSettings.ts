import { useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";

interface ConfigValues {
  apiKey?: string;
  endpoint?: string;
  projectId?: string;
  languageModel?: string;
  embeddingModel?: string;
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

      // Map provider-specific API keys
      if (config.apiKey) {
        if (provider === "openai") {
          updatedSettings.openai_api_key = config.apiKey;
        } else if (provider === "anthropic") {
          updatedSettings.anthropic_api_key = config.apiKey;
        } else if (provider === "watsonx") {
          updatedSettings.watsonx_api_key = config.apiKey;
        }
      }

      // Map provider-specific endpoints
      if (config.endpoint) {
        if (provider === "watsonx") {
          updatedSettings.watsonx_endpoint = config.endpoint;
        } else if (provider === "ollama") {
          updatedSettings.ollama_endpoint = config.endpoint;
        }
      }

      // Map project ID (WatsonX only)
      if (config.projectId && provider === "watsonx") {
        updatedSettings.watsonx_project_id = config.projectId;
      }

      return updatedSettings;
    });
  }, [
    provider,
    config.apiKey,
    config.endpoint,
    config.projectId,
    config.languageModel,
    config.embeddingModel,
    setSettings,
    isEmbedding,
  ]);
}
