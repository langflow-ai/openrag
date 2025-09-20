import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOllamaModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { useDebouncedValue } from "@/lib/debounce";
import { AdvancedOnboarding } from "./advanced";
import { ModelSelector } from "./model-selector";

export function OllamaOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
}: {
  setSettings: (settings: OnboardingVariables) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const [endpoint, setEndpoint] = useState("");
  const debouncedEndpoint = useDebouncedValue(endpoint, 500);

  // Fetch models from API when endpoint is provided (debounced)
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOllamaModelsQuery(
    debouncedEndpoint ? { endpoint: debouncedEndpoint } : undefined,
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
    "ollama",
    {
      endpoint,
      languageModel,
      embeddingModel,
    },
    setSettings,
  );

  // Check validation state based on models query
  const isConnecting = debouncedEndpoint && isLoadingModels;
  const hasConnectionError = debouncedEndpoint && modelsError;
  const hasNoModels =
    modelsData &&
    !modelsData.language_models?.length &&
    !modelsData.embedding_models?.length;
  const isValidConnection =
    modelsData &&
    (modelsData.language_models?.length > 0 ||
      modelsData.embedding_models?.length > 0);

  return (
    <>
      <div className="space-y-1">
        <LabelInput
          label="Ollama Endpoint"
          helperText="The endpoint for your Ollama server."
          id="api-endpoint"
          required
          placeholder="http://localhost:11434"
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
        />
        {isConnecting && (
          <p className="text-sm text-muted-foreground">
            Connecting to Ollama server...
          </p>
        )}
        {hasConnectionError && (
          <p className="text-sm text-red-500">
            Cannot connect to Ollama server. Please check the endpoint.
          </p>
        )}
        {hasNoModels && (
          <p className="text-sm text-yellow-600">
            No models found. Please install some models on your Ollama server.
          </p>
        )}
        {isValidConnection && (
          <p className="text-sm text-green-600">Connected successfully</p>
        )}
      </div>
      <LabelWrapper
        label="Embedding model"
        helperText="The embedding model for your Ollama server."
        id="embedding-model"
        required={true}
      >
        <ModelSelector
          options={embeddingModels}
          icon={<OllamaLogo className="w-4 h-4" />}
          value={embeddingModel}
          onValueChange={setEmbeddingModel}
        />
      </LabelWrapper>
      <LabelWrapper
        label="Language model"
        helperText="The embedding model for your Ollama server."
        id="embedding-model"
        required={true}
      >
        <ModelSelector
          options={languageModels}
          icon={<OllamaLogo className="w-4 h-4" />}
          value={languageModel}
          onValueChange={setLanguageModel}
        />
      </LabelWrapper>

      <AdvancedOnboarding
        sampleDataset={sampleDataset}
        setSampleDataset={handleSampleDatasetChange}
      />
    </>
  );
}
