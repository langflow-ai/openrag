import type { Dispatch, SetStateAction } from "react";
import { useState } from "react";
import OpenAILogo from "@/components/icons/openai-logo";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOpenAIModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../_hooks/useModelSelection";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";
import { AdvancedOnboarding } from "./advanced";

export function OpenAIOnboarding({
  setSettings,
  isEmbedding = false,
  hasEnvApiKey = false,
  alreadyConfigured = false,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  hasEnvApiKey?: boolean;
  alreadyConfigured?: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [getFromEnv, setGetFromEnv] = useState(
    hasEnvApiKey && !alreadyConfigured,
  );
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    isFetching: isFetchingModels,
    error: modelsError,
  } = useGetOpenAIModelsQuery(
    getFromEnv
      ? { useEnvKey: true }
      : debouncedApiKey
        ? { apiKey: debouncedApiKey, useEnvKey: false }
        : undefined,
    {
      enabled: debouncedApiKey !== "" || getFromEnv || alreadyConfigured,
    },
  );

  const showModelsError =
    !!modelsError && !isLoadingModels && !isFetchingModels;

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

  useUpdateSettings(
    "openai",
    {
      apiKey: getFromEnv || alreadyConfigured ? undefined : apiKey,
      clearApiKey: getFromEnv,
      languageModel,
      embeddingModel,
    },
    setSettings,
    isEmbedding,
  );

  return (
    <>
      <div className="space-y-5">
        {!alreadyConfigured && (
          <LabelWrapper
            label="Use environment OpenAI API key"
            id="get-api-key"
            description="Reuse the key from your environment config. Turn off to enter a different key."
            flex
          >
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <Switch
                    checked={getFromEnv}
                    data-testid="get-from-env-switch"
                    onCheckedChange={handleGetFromEnvChange}
                    disabled={!hasEnvApiKey}
                  />
                </div>
              </TooltipTrigger>
              {!hasEnvApiKey && (
                <TooltipContent>
                  OpenAI API key not detected in the environment.
                </TooltipContent>
              )}
            </Tooltip>
          </LabelWrapper>
        )}
        {(!getFromEnv || alreadyConfigured) && (
          <div className="space-y-1">
            <LabelInput
              label="OpenAI API key"
              helperText="The API key for your OpenAI account."
              className={showModelsError ? "!border-destructive" : ""}
              id="api-key"
              type="password"
              required
              placeholder={
                alreadyConfigured
                  ? "sk-•••••••••••••••••••••••••••••••••••••••••"
                  : "sk-..."
              }
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              disabled={false}
            />
            {alreadyConfigured && (
              <p className="text-mmd text-muted-foreground">
                Existing OpenAI key detected. You can reuse it or enter a new
                one.
              </p>
            )}
            {(isLoadingModels || isFetchingModels) && (
              <p className="text-mmd text-muted-foreground">
                Validating API key...
              </p>
            )}
            {showModelsError && (
              <p className="text-mmd text-destructive">{modelsError.message}</p>
            )}
          </div>
        )}
      </div>
      <AdvancedOnboarding
        icon={<OpenAILogo className="w-4 h-4" />}
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        languageModel={languageModel}
        embeddingModel={embeddingModel}
        setLanguageModel={setLanguageModel}
        setEmbeddingModel={setEmbeddingModel}
      />
    </>
  );
}
