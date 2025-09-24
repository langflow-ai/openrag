import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import OpenAILogo from "@/components/logo/openai-logo";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOpenAIModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
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
          type="password"
          required
          placeholder="sk-..."
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        {isLoadingModels && (
          <p className="text-mmd text-muted-foreground">
            Validating API key...
          </p>
        )}
        {modelsError && (
          <p className="text-mmd text-accent-amber-foreground">
            Invalid API key
          </p>
        )}
        {modelsData &&
          (modelsData.language_models?.length > 0 ||
            modelsData.embedding_models?.length > 0) && (
            <p className="text-mmd text-accent-emerald-foreground">
              API Key is valid
            </p>
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
