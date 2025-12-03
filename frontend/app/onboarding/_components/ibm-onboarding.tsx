import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import IBMLogo from "@/components/icons/ibm-logo";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetIBMModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../_hooks/useModelSelection";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";
import { ModelSelector } from "./model-selector";

export function IBMOnboarding({
  isEmbedding = false,
  setSettings,
  sampleDataset,
  setSampleDataset,
  setIsLoadingModels,
  alreadyConfigured = false,
  existingEndpoint,
  existingProjectId,
  hasEnvApiKey = false,
}: {
  isEmbedding?: boolean;
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
  setIsLoadingModels?: (isLoading: boolean) => void;
  alreadyConfigured?: boolean;
  existingEndpoint?: string;
  existingProjectId?: string;
  hasEnvApiKey?: boolean;
}) {
  const [endpoint, setEndpoint] = useState(
    alreadyConfigured ? "" : (existingEndpoint || "https://us-south.ml.cloud.ibm.com"),
  );
  const [apiKey, setApiKey] = useState("");
  const [getFromEnv, setGetFromEnv] = useState(
    hasEnvApiKey && !alreadyConfigured,
  );
  const [projectId, setProjectId] = useState(
    alreadyConfigured ? "" : (existingProjectId || ""),
  );

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
    {
      endpoint: debouncedEndpoint ? debouncedEndpoint : undefined,
      apiKey: getFromEnv ? "" : (debouncedApiKey ? debouncedApiKey : undefined),
      projectId: debouncedProjectId ? debouncedProjectId : undefined,
    },
    {
      enabled:
        !!debouncedEndpoint ||
        !!debouncedApiKey ||
        !!debouncedProjectId ||
        getFromEnv ||
        alreadyConfigured,
    },
  );

  // Use custom hook for model selection logic
  const {
    languageModel,
    embeddingModel,
    setLanguageModel,
    setEmbeddingModel,
    languageModels,
    embeddingModels,
  } = useModelSelection(modelsData, isEmbedding);

  const handleGetFromEnvChange = (fromEnv: boolean) => {
    setGetFromEnv(fromEnv);
    if (fromEnv) {
      setApiKey("");
    }
    setEmbeddingModel?.("");
    setLanguageModel?.("");
  };

  const handleSampleDatasetChange = (dataset: boolean) => {
    setSampleDataset(dataset);
  };

  useEffect(() => {
    setIsLoadingModels?.(isLoadingModels);
  }, [isLoadingModels, setIsLoadingModels]);

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
    isEmbedding,
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
          <div className="space-y-1">
            <ModelSelector
              options={alreadyConfigured ? [] : options}
              value={endpoint}
              custom
              onValueChange={alreadyConfigured ? () => {} : setEndpoint}
              searchPlaceholder="Search endpoint..."
              noOptionsPlaceholder={
                alreadyConfigured
                  ? "https://•••••••••••••••••••••••••••••••••••••••••"
                  : "No endpoints available"
              }
              placeholder="Select endpoint..."
            />
            {alreadyConfigured && (
              <p className="text-mmd text-muted-foreground">
                Reusing endpoint from model provider selection.
              </p>
            )}
          </div>
        </LabelWrapper>

        <div className="space-y-1">
          <LabelInput
            label="watsonx Project ID"
            helperText="Project ID for the model"
            id="project-id"
            required
            placeholder={
              alreadyConfigured ? "••••••••••••••••••••••••" : "your-project-id"
            }
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={alreadyConfigured}
          />
          {alreadyConfigured && (
            <p className="text-mmd text-muted-foreground">
              Reusing project ID from model provider selection.
            </p>
          )}
        </div>
        <LabelWrapper
          label="Use environment watsonx API key"
          id="get-api-key"
          description="Reuse the key from your environment config. Turn off to enter a different key."
          flex
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <div>
                <Switch
                  checked={getFromEnv}
                  onCheckedChange={handleGetFromEnvChange}
                  disabled={!hasEnvApiKey || alreadyConfigured}
                />
              </div>
            </TooltipTrigger>
            {!hasEnvApiKey && !alreadyConfigured && (
              <TooltipContent>
                watsonx API key not detected in the environment.
              </TooltipContent>
            )}
          </Tooltip>
        </LabelWrapper>
        {!getFromEnv && !alreadyConfigured && (
          <div className="space-y-1">
            <LabelInput
              label="watsonx API key"
              helperText="API key to access watsonx.ai"
              className={modelsError ? "!border-destructive" : ""}
              id="api-key"
              type="password"
              required
              placeholder="your-api-key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {isLoadingModels && (
              <p className="text-mmd text-muted-foreground">
                Validating API key...
              </p>
            )}
            {modelsError && (
              <p className="text-mmd text-destructive">
                Invalid watsonx API key. Verify or replace the key.
              </p>
            )}
          </div>
        )}
        {alreadyConfigured && (
          <div className="space-y-1">
            <LabelInput
              label="watsonx API key"
              helperText="API key to access watsonx.ai"
              id="api-key"
              type="password"
              required
              placeholder="•••••••••••••••••••••••••••••••••••••••••"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              disabled={true}
            />
            <p className="text-mmd text-muted-foreground">
              Reusing API key from model provider selection.
            </p>
          </div>
        )}
        {getFromEnv && isLoadingModels && (
          <p className="text-mmd text-muted-foreground">
            Validating configuration...
          </p>
        )}
        {getFromEnv && modelsError && (
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
