import { useEffect, useState } from "react";
import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useGetOpenAIModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AnimatedConditional } from "@/components/animated-conditional";
import OpenAILogo from "@/components/logo/openai-logo";

export interface OpenAISettingsFormData {
  apiKey: string;
  llmModel: string;
  embeddingModel: string;
}

export function OpenAISettingsForm() {
  const [useExistingKey, setUseExistingKey] = useState(true);
  const {
    control,
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


  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOpenAIModelsQuery(
    {
      apiKey: useExistingKey ? "" : debouncedApiKey,
    }
  );

  useEffect(() => {
    if (modelsError || isLoadingModels) {
      setValue("llmModel", "");
      setValue("embeddingModel", "");
    }
  }, [modelsError, isLoadingModels, setValue]);

  const languageModels = modelsData?.language_models || [];
  const embeddingModels = modelsData?.embedding_models || [];

  return (
    <div className="space-y-4">
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
      <AnimatedConditional isOpen={!useExistingKey} duration={0.2} vertical>
        <div className="space-y-2">
          <LabelWrapper
            label="OpenAI API key"
            helperText="The API key for your OpenAI account"
            required
            id="api-key"
          >
            <Input
              {...register("apiKey", {
                required: !useExistingKey ? "API key is required" : false,
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
        <p className="text-sm text-muted-foreground">
          Validating API key...
        </p>
      )}
      {modelsError && (
        <p className="text-sm text-destructive">
          Invalid OpenAI API key. Verify or replace the key.
        </p>
      )}

      <div className="space-y-2">
        <LabelWrapper
          label="Embedding model"
          helperText="Model used for knowledge ingest and retrieval"
          id="embedding-model"
          required={true}
        >
          <Controller
            control={control}
            name="embeddingModel"
            rules={{ required: "Embedding model is required" }}
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={isLoadingModels || !embeddingModels.length}
              >
                <SelectTrigger id="embedding-model">
                  <div className="flex items-center gap-2">
                    <OpenAILogo className="w-4 h-4" />
                    <SelectValue
                      placeholder={
                        isLoadingModels
                          ? "Loading models..."
                          : embeddingModels.length
                          ? "Select an embedding model"
                          : "No embedding models found"
                      }
                    />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {embeddingModels.map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </LabelWrapper>
        {errors.embeddingModel && (
          <p className="text-sm text-destructive">
            {errors.embeddingModel.message}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Language model"
          helperText="Model used for chat"
          id="language-model"
          required={true}
        >
          <Controller
            control={control}
            name="llmModel"
            rules={{ required: "Language model is required" }}
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={isLoadingModels || !languageModels.length}
              >
                <SelectTrigger id="language-model">
                  <div className="flex items-center gap-2">
                    <OpenAILogo className="w-4 h-4" />
                    <SelectValue
                      placeholder={
                        isLoadingModels
                          ? "Loading models..."
                          : languageModels.length
                          ? "Select a language model"
                          : "No language models found"
                      }
                    />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {languageModels.map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </LabelWrapper>
        {errors.llmModel && (
          <p className="text-sm text-destructive">{errors.llmModel.message}</p>
        )}
      </div>
    </div>
  );
}

