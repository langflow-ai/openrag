import { useEffect, useState } from "react";
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
  setIsLoadingModels,
  setLoadingStatus,
  onValidationChange,
}: {
  setSettings: (settings: OnboardingVariables) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
  setIsLoadingModels?: (isLoading: boolean) => void;
  setLoadingStatus?: (status: string[]) => void;
  onValidationChange?: (validation: { hasError: boolean }) => void;
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
      : undefined
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
    setSettings
  );

  // Notify parent about loading state
  useEffect(() => {
    setIsLoadingModels?.(isLoadingModels);

    // Set detailed loading status
    if (isLoadingModels) {
      const status = [
        "Connecting to IBM watsonx.ai",
        "Fetching language models",
        "Fetching embedding models",
      ];
      setLoadingStatus?.(status);
    } else {
      setLoadingStatus?.([]);
    }
  }, [isLoadingModels, setIsLoadingModels, setLoadingStatus]);

  // Notify parent about validation state changes
  useEffect(() => {
    onValidationChange?.({
      hasError: !!modelsError,
    });
  }, [modelsError, onValidationChange]);
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
            custom
            onValueChange={setEndpoint}
            searchPlaceholder="Search endpoint..."
            noOptionsPlaceholder="No endpoints available"
            placeholder="Select endpoint..."
          />
        </LabelWrapper>
        <LabelInput
          label="watsonx Project ID"
          helperText="Project ID for the model"
          id="project-id"
          required
          placeholder="your-project-id"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        />
        <LabelInput
          label="watsonx API key"
          helperText="API key to access watsonx.ai"
          id="api-key"
          type="password"
          required
          placeholder="your-api-key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
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
