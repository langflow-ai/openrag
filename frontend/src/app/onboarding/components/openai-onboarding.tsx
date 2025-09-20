import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import OpenAILogo from "@/components/logo/openai-logo";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOpenAIModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { useDebouncedValue } from "@/lib/debounce";
import { AdvancedOnboarding } from "./advanced";

export function OpenAIOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
}: {
  setSettings: (settings: OnboardingVariables) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  // Fetch models from API when API key is provided
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOpenAIModelsQuery(
    debouncedApiKey ? { apiKey: debouncedApiKey } : undefined,
  );
  // Use custom hook for model selection logic
  const {
    languageModel,
    embeddingModel,
    setLanguageModel,
    setEmbeddingModel,
    languageModels,
    embeddingModels,
  } = useModelSelection(modelsData);
  const handleSampleDatasetChange = (dataset: boolean) => {
    setSampleDataset(dataset);
  };

  // Update settings when values change
  useUpdateSettings(
    "openai",
    {
      apiKey,
      languageModel,
      embeddingModel,
    },
    setSettings,
  );
  return (
    <>
      <div className="space-y-1">
        <LabelInput
          label="OpenAI API key"
          helperText="The API key for your OpenAI account."
          id="api-key"
          required
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">Validating API key...</p>
        )}
        {modelsError && (
          <p className="text-sm text-red-500">
            Invalid API key or configuration
          </p>
        )}
        {modelsData &&
          (modelsData.language_models?.length > 0 ||
            modelsData.embedding_models?.length > 0) && (
            <p className="text-sm text-green-600">Configuration is valid</p>
          )}
      </div>
      <AdvancedOnboarding
        icon={<OpenAILogo className="w-4 h-4" />}
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        languageModel={languageModel}
        embeddingModel={embeddingModel}
        sampleDataset={sampleDataset}
        setLanguageModel={setLanguageModel}
        setSampleDataset={handleSampleDatasetChange}
        setEmbeddingModel={setEmbeddingModel}
      />
    </>
  );
}
