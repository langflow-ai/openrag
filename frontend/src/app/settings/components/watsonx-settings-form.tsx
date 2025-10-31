import { useEffect, useState } from "react";
import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useGetIBMModelsQuery } from "@/app/api/queries/useGetModelsQuery";
import { useDebouncedValue } from "@/lib/debounce";
import { AnimatedConditional } from "@/components/animated-conditional";
import IBMLogo from "@/components/logo/ibm-logo";
import { ModelSelectors } from "./model-selectors";
import { ModelSelector } from "@/app/onboarding/components/model-selector";

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

export function WatsonxSettingsForm({
  isCurrentProvider = false,
}: {
  isCurrentProvider: boolean;
}) {
  const [useExistingKey, setUseExistingKey] = useState(true);
  const {
    control,
    register,
    watch,
    setValue,
    clearErrors,
    formState: { errors },
  } = useFormContext<WatsonxSettingsFormData>();

  const endpoint = watch("endpoint");
  const apiKey = watch("apiKey");
  const projectId = watch("projectId");

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

  // Clear form errors when useExistingKey changes
  useEffect(() => {
    clearErrors("apiKey");
  }, [useExistingKey, clearErrors]);

  const shouldFetchModels = isCurrentProvider
    ? useExistingKey
      ? !!debouncedEndpoint && !!debouncedProjectId
      : !!debouncedEndpoint && !!debouncedApiKey && !!debouncedProjectId
    : !!debouncedEndpoint && !!debouncedProjectId && !!debouncedApiKey;

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetIBMModelsQuery(
    {
      endpoint: debouncedEndpoint,
      apiKey: useExistingKey ? "" : debouncedApiKey,
      projectId: debouncedProjectId,
    },
    {
      enabled: shouldFetchModels,
    }
  );

  const languageModels = modelsData?.language_models || [];
  const embeddingModels = modelsData?.embedding_models || [];

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <LabelWrapper
          label="watsonx.ai API Endpoint"
          helperText="Base URL of the API"
          id="api-endpoint"
          required
        >
          <Controller
            control={control}
            name="endpoint"
            rules={{ required: "API endpoint is required" }}
            render={({ field }) => (
              <ModelSelector
                options={endpointOptions.map((option) => ({
                  value: option.value,
                  label: option.label,
                }))}
                value={field.value}
                custom
                onValueChange={field.onChange}
                searchPlaceholder="Search endpoint..."
                noOptionsPlaceholder="No endpoints available"
                placeholder="Select endpoint..."
                hasError={!!errors.endpoint || !!modelsError}
              />
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
            className={
              errors.projectId || modelsError ? "!border-destructive" : ""
            }
            id="project-id"
            type="text"
            placeholder="your-project-id"
          />
        </LabelWrapper>
        {errors.projectId && (
          <p className="text-sm text-destructive">{errors.projectId.message}</p>
        )}
      </div>
      <div className={useExistingKey ? "space-y-3" : "space-y-2"}>
        {isCurrentProvider && (
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
        )}
        <AnimatedConditional
          isOpen={!useExistingKey}
          duration={0.2}
          vertical
          className={!useExistingKey ? "!mt-4" : "!mt-0"}
        >
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
            <p className="text-sm text-destructive mt-2">
              {errors.apiKey.message}
            </p>
          )}
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
      </div>
      <ModelSelectors
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        isLoadingModels={isLoadingModels}
        logo={<IBMLogo className="w-4 h-4 text-[#1063FE]" />}
      />
    </div>
  );
}
