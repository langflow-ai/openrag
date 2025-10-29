import { useEffect, useState } from "react";
import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AnimatedConditional } from "@/components/animated-conditional";
import IBMLogo from "@/components/logo/ibm-logo";

export interface WatsonxSettingsFormData {
  endpoint: string;
  apiKey: string;
  projectId: string;
  llmModel: string;
  embeddingModel: string;
}

const endpointOptions = [
  {
    value: "https://us-south.ml.cloud.ibm.com",
    label: "https://us-south.ml.cloud.ibm.com",
  },
  {
    value: "https://eu-de.ml.cloud.ibm.com",
    label: "https://eu-de.ml.cloud.ibm.com",
  },
  {
    value: "https://eu-gb.ml.cloud.ibm.com",
    label: "https://eu-gb.ml.cloud.ibm.com",
  },
  {
    value: "https://au-syd.ml.cloud.ibm.com",
    label: "https://au-syd.ml.cloud.ibm.com",
  },
  {
    value: "https://jp-tok.ml.cloud.ibm.com",
    label: "https://jp-tok.ml.cloud.ibm.com",
  },
  {
    value: "https://ca-tor.ml.cloud.ibm.com",
    label: "https://ca-tor.ml.cloud.ibm.com",
  },
];

export function WatsonxSettingsForm() {
  const [useExistingKey, setUseExistingKey] = useState(true);
  const {
    control,
    register,
    getValues,
    watch,
    setValue,
    formState: { errors },
  } = useFormContext<WatsonxSettingsFormData>();

  const endpoint = watch("endpoint");
  const apiKey = watch("apiKey");
  const projectId = watch("projectId");

  console.log("getValues", getValues());

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);
  const debouncedProjectId = useDebouncedValue(projectId, 500);

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
  } = useGetIBMModelsQuery({
    endpoint: debouncedEndpoint,
    // Don't pass API key when using existing - backend will use stored key
    apiKey: useExistingKey ? "" : debouncedApiKey,
    projectId: debouncedProjectId,
  });

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
          label="watsonx.ai API Endpoint"
          helperText="Base URL of the API"
          required
          id="endpoint"
        >
          <Controller
            control={control}
            name="endpoint"
            rules={{ required: "API endpoint is required" }}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="endpoint">
                  <SelectValue placeholder="Select endpoint..." />
                </SelectTrigger>
                <SelectContent>
                  {endpointOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </LabelWrapper>
        {errors.endpoint && (
          <p className="text-sm text-destructive">{errors.endpoint.message}</p>
        )}
      </div>

      <div className="space-y-2">
        <LabelWrapper
          label="watsonx Project ID"
          helperText="Project ID for the model"
          required
          id="project-id"
        >
          <Input
            {...register("projectId", {
              required: "Project ID is required",
            })}
            className={errors.projectId ? "!border-destructive" : ""}
            id="project-id"
            type="text"
            placeholder="your-project-id"
          />
        </LabelWrapper>
        {errors.projectId && (
          <p className="text-sm text-destructive">{errors.projectId.message}</p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Use existing watsonx API key"
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
            label="watsonx API key"
            helperText="API key to access watsonx.ai"
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
              placeholder="your-api-key"
            />
          </LabelWrapper>
          {errors.apiKey && (
            <p className="text-sm text-destructive">{errors.apiKey.message}</p>
          )}
        </div>
      </AnimatedConditional>
      {isLoadingModels && (
        <p className="text-sm text-muted-foreground">
          Validating configuration...
        </p>
      )}
      {modelsError && (
        <p className="text-sm text-destructive">
          Connection failed. Check your configuration.
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
                    <IBMLogo className="w-4 h-4 text-[#1063FE]" />
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
                    <IBMLogo className="w-4 h-4 text-[#1063FE]" />
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
