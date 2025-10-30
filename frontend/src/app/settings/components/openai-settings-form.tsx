import { useEffect, useState } from "react";
import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useGetOpenAIModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import { AnimatedConditional } from "@/components/animated-conditional";
import OpenAILogo from "@/components/logo/openai-logo";
import { ModelSelectors } from "./model-selectors";

export interface OpenAISettingsFormData {
  apiKey: string;
  llmModel: string;
  embeddingModel: string;
}

export function OpenAISettingsForm({
  isCurrentProvider = false,
}: {
  isCurrentProvider: boolean;
}) {
  const [useExistingKey, setUseExistingKey] = useState(true);
  const {
    register,
    watch,
    setValue,
    formState: { errors },
  } = useFormContext<OpenAISettingsFormData>();

  const apiKey = watch("apiKey");
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  // Handle switch change
  const handleUseExistingKeyChange = (checked: boolean) => {
    setUseExistingKey(checked);
    if (checked) {
      // Clear the API key field when using existing key
      setValue("apiKey", "");
    }
  };

  const shouldFetchModels = isCurrentProvider
    ? useExistingKey
      ? true
      : !!debouncedApiKey
    : !!debouncedApiKey;

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOpenAIModelsQuery(
    {
      apiKey: useExistingKey ? "" : debouncedApiKey,
    },
    {
      enabled: shouldFetchModels,
    }
  );

  const languageModels = modelsData?.language_models || [];
  const embeddingModels = modelsData?.embedding_models || [];

  return (
    <div className="space-y-4">
      {isCurrentProvider && (
        <div className="space-y-2">
          <LabelWrapper
            label="Use existing OpenAI API key"
            id="use-existing-key"
            description="Reuse the key from your environment config. Turn off to enter a different key."
            flex
          >
            <Switch
              checked={useExistingKey}
              onCheckedChange={handleUseExistingKeyChange}
            />
          </LabelWrapper>
        </div>
      )}
      <AnimatedConditional
        isOpen={!isCurrentProvider || !useExistingKey}
        duration={0.2}
        vertical
      >
        <div className="space-y-2">
          <LabelWrapper
            label="OpenAI API key"
            helperText="The API key for your OpenAI account"
            required
            id="api-key"
          >
            <Input
              {...register("apiKey", {
                required: !isCurrentProvider || !useExistingKey ? "API key is required" : false,
              })}
              className={
                errors.apiKey || modelsError ? "!border-destructive" : ""
              }
              id="api-key"
              type="password"
              placeholder="sk-..."
            />
          </LabelWrapper>
          {errors.apiKey && (
            <p className="text-sm text-destructive">{errors.apiKey.message}</p>
          )}
        </div>
      </AnimatedConditional>
      {isLoadingModels && (
        <p className="text-sm text-muted-foreground">Validating API key...</p>
      )}
      {modelsError && (
        <p className="text-sm text-destructive">
          Invalid OpenAI API key. Verify or replace the key.
        </p>
      )}

      <ModelSelectors
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        isLoadingModels={isLoadingModels}
        logo={<OpenAILogo className="w-4 h-4" />}
      />
    </div>
  );
}

