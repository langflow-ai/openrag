import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { useGetOllamaModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import OllamaLogo from "@/components/logo/ollama-logo";
import { ModelSelectors } from "./model-selectors";

export interface OllamaSettingsFormData {
  endpoint: string;
  llmModel: string;
  embeddingModel: string;
}

export function OllamaSettingsForm() {
  const {
    register,
    watch,
    formState: { errors },
  } = useFormContext<OllamaSettingsFormData>();

  const endpoint = watch("endpoint");
  const debouncedEndpoint = useDebouncedValue(endpoint, 500);

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOllamaModelsQuery(
    {
      endpoint: debouncedEndpoint,
    },
    {
      enabled: !!endpoint,
    }
  );

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
              value: "http://localhost:11434",
              required: "Ollama base URL is required",
            })}
            className={errors.endpoint ? "!border-destructive" : ""}
            id="endpoint"
            type="text"
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

      <ModelSelectors
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        isLoadingModels={isLoadingModels}
        logo={<OllamaLogo className="w-4 h-4" />}
      />
    </div>
  );
}
