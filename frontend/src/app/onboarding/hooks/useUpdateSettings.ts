import { useEffect } from "react";
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
  setSettings: (settings: OnboardingVariables) => void,
) {
  useEffect(() => {
    const updatedSettings: OnboardingVariables = {
      model_provider: provider,
      embedding_model: "",
      llm_model: "",
    };

    // Set language model if provided
    if (config.languageModel) {
      updatedSettings.llm_model = config.languageModel;
    }

    // Set embedding model if provided
    if (config.embeddingModel) {
      updatedSettings.embedding_model = config.embeddingModel;
    }

    // Set API key if provided
    if (config.apiKey) {
      updatedSettings.api_key = config.apiKey;
    }

    // Set endpoint and project ID if provided
    if (config.endpoint) {
      updatedSettings.endpoint = config.endpoint;
    }

    if (config.projectId) {
      updatedSettings.project_id = config.projectId;
    }

    setSettings(updatedSettings);
  }, [
    provider,
    config.apiKey,
    config.endpoint,
    config.projectId,
    config.languageModel,
    config.embeddingModel,
    setSettings,
  ]);
}
