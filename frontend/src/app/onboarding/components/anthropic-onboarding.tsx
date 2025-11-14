import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import AnthropicLogo from "@/components/logo/anthropic-logo";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetAnthropicModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../hooks/useModelSelection";
import { useUpdateSettings } from "../hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";

export function AnthropicOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
  setIsLoadingModels,
  isEmbedding = false,
  hasEnvApiKey = false,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
  setIsLoadingModels?: (isLoading: boolean) => void;
  isEmbedding?: boolean;
  hasEnvApiKey?: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [getFromEnv, setGetFromEnv] = useState(hasEnvApiKey);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  // Fetch models from API when API key is provided
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetAnthropicModelsQuery(
    getFromEnv
      ? { apiKey: "" }
      : debouncedApiKey
        ? { apiKey: debouncedApiKey }
        : undefined,
    { enabled: debouncedApiKey !== "" || getFromEnv },
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
  const handleSampleDatasetChange = (dataset: boolean) => {
    setSampleDataset(dataset);
  };

  const handleGetFromEnvChange = (fromEnv: boolean) => {
    setGetFromEnv(fromEnv);
    if (fromEnv) {
      setApiKey("");
    }
    setEmbeddingModel?.("");
    setLanguageModel?.("");
  };

  useEffect(() => {
    setIsLoadingModels?.(isLoadingModels);
  }, [isLoadingModels, setIsLoadingModels]);

  // Update settings when values change
  useUpdateSettings(
    "anthropic",
    {
      apiKey,
      languageModel,
      embeddingModel,
    },
    setSettings,
    isEmbedding,
  );

  return (
    <>
      <div className="space-y-5">
        <LabelWrapper
          label="Use environment Anthropic API key"
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
                  disabled={!hasEnvApiKey}
                />
              </div>
            </TooltipTrigger>
            {!hasEnvApiKey && (
              <TooltipContent>
                Anthropic API key not detected in the environment.
              </TooltipContent>
            )}
          </Tooltip>
        </LabelWrapper>
        {!getFromEnv && (
          <div className="space-y-1">
            <LabelInput
              label="Anthropic API key"
              helperText="The API key for your Anthropic account."
              className={modelsError ? "!border-destructive" : ""}
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
              <p className="text-mmd text-destructive">
                Invalid Anthropic API key. Verify or replace the key.
              </p>
            )}
          </div>
        )}
      </div>
      <AdvancedOnboarding
        icon={<AnthropicLogo className="w-4 h-4 text-[#D97757" />}
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
