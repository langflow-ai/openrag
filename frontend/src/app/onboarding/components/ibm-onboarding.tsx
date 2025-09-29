import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import IBMLogo from "@/components/logo/ibm-logo";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetIBMModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";
import { ModelSelector } from "./model-selector";

export function IBMOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
}: {
  setSettings: (settings: OnboardingVariables) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const [endpoint, setEndpoint] = useState("https://us-south.ml.cloud.ibm.com");
  const [apiKey, setApiKey] = useState("");
  const [projectId, setProjectId] = useState("");

  const options = [
    {
      value: "https://us-south.ml.cloud.ibm.com",
      label: "https://us-south.ml.cloud.ibm.com",
      default: true,
    },
    {
      value: "https://eu-de.ml.cloud.ibm.com",
      label: "https://eu-de.ml.cloud.ibm.com",
      default: false,
    },
    {
      value: "https://eu-gb.ml.cloud.ibm.com",
      label: "https://eu-gb.ml.cloud.ibm.com",
      default: false,
    },
    {
      value: "https://au-syd.ml.cloud.ibm.com",
      label: "https://au-syd.ml.cloud.ibm.com",
      default: false,
    },
    {
      value: "https://jp-tok.ml.cloud.ibm.com",
      label: "https://jp-tok.ml.cloud.ibm.com",
      default: false,
    },
    {
      value: "https://ca-tor.ml.cloud.ibm.com",
      label: "https://ca-tor.ml.cloud.ibm.com",
      default: false,
    },
  ];
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
    "watsonx",
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
        <LabelWrapper
          label="watsonx.ai API Endpoint"
          helperText="Base URL of the API"
          id="api-endpoint"
          required
        >
          <ModelSelector
            options={options}
            value={endpoint}
            onValueChange={setEndpoint}
            searchPlaceholder="Search endpoint..."
            noOptionsPlaceholder="No endpoints available"
            placeholder="Select endpoint..."
          />
        </LabelWrapper>
        <LabelInput
          label="IBM API key"
          helperText="The API key for your watsonx.ai account."
          id="api-key"
          type="password"
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
            Connection failed. Check your configuration.
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
