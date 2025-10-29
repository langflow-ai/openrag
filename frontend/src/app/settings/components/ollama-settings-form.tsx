import { useEffect } from "react";
import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { useGetOllamaModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import OllamaLogo from "@/components/logo/ollama-logo";

export interface OllamaSettingsFormData {
  endpoint: string;
  llmModel: string;
  embeddingModel: string;
}

export function OllamaSettingsForm() {
  const {
    control,
    register,
    watch,
    setValue,
    formState: { errors, dirtyFields },
  } = useFormContext<OllamaSettingsFormData>();

  const endpoint = watch("endpoint");

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);

  // Check if endpoint field is dirty
  const credentialsAreDirty = dirtyFields.endpoint;

  // Fetch models when endpoint is provided AND field is dirty
  const shouldFetchModels = credentialsAreDirty ? !!debouncedEndpoint : false;

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOllamaModelsQuery(
    shouldFetchModels
      ? {
          endpoint: debouncedEndpoint,
        }
      : undefined
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
          label="Ollama Base URL"
          helperText="Base URL of your Ollama server"
          required
          id="endpoint"
        >
          <Input
            {...register("endpoint", {
              required: "Ollama base URL is required",
            })}
            className={errors.endpoint ? "!border-destructive" : ""}
            id="endpoint"
            type="text"
            placeholder="http://localhost:11434"
          />
        </LabelWrapper>
        {errors.endpoint && (
          <p className="text-sm text-destructive">{errors.endpoint.message}</p>
        )}
      </div>
      {isLoadingModels && (
        <p className="text-sm text-muted-foreground">
          Validating connection...
        </p>
      )}
      {modelsError && (
        <p className="text-sm text-destructive">
          Connection failed. Check your Ollama server URL.
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
                    <OllamaLogo className="w-4 h-4" />
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
                    <OllamaLogo className="w-4 h-4" />
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

