import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import IBMLogo from "@/components/logo/ibm-logo";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetIBMModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";

export function IBMOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
}: {
  setSettings: (settings: OnboardingVariables) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const [endpoint, setEndpoint] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [projectId, setProjectId] = useState("");

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);
  const debouncedProjectId = useDebouncedValue(projectId, 500);

  // Fetch models from API when all credentials are provided
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetIBMModelsQuery(
    debouncedEndpoint && debouncedApiKey && debouncedProjectId
      ? {
          endpoint: debouncedEndpoint,
          apiKey: debouncedApiKey,
          projectId: debouncedProjectId,
        }
      : undefined,
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
    "ibm",
    {
      endpoint,
      apiKey,
      projectId,
      languageModel,
      embeddingModel,
    },
    setSettings,
  );
  return (
    <>
      <div className="space-y-4">
        <LabelInput
          label="watsonx.ai API Endpoint"
          helperText="The API endpoint for your watsonx.ai account."
          id="api-endpoint"
          required
          placeholder="https://us-south.ml.cloud.ibm.com"
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
        />
        <LabelInput
          label="IBM API key"
          helperText="The API key for your watsonx.ai account."
          id="api-key"
          required
          placeholder="your-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <LabelInput
          label="IBM Project ID"
          helperText="The project ID for your watsonx.ai account."
          id="project-id"
          required
          placeholder="your-project-id"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        />
        {isLoadingModels && (
          <p className="text-mmd text-muted-foreground">
            Validating configuration...
          </p>
        )}
        {modelsError && (
          <p className="text-mmd text-accent-amber-foreground">
            Invalid configuration or connection failed
          </p>
        )}
        {modelsData &&
          (modelsData.language_models?.length > 0 ||
            modelsData.embedding_models?.length > 0) && (
            <p className="text-mmd text-accent-emerald-foreground">
              Configuration is valid
            </p>
          )}
      </div>
      <AdvancedOnboarding
        icon={<IBMLogo className="w-4 h-4" />}
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        languageModel={languageModel}
        embeddingModel={embeddingModel}
        sampleDataset={sampleDataset}
        setLanguageModel={setLanguageModel}
        setEmbeddingModel={setEmbeddingModel}
        setSampleDataset={handleSampleDatasetChange}
      />
    </>
  );
}
