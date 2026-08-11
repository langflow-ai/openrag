import { Controller, useFormContext } from "react-hook-form";
import { ModelSelector } from "@/app/onboarding/_components/model-selector";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";

export interface AzureOpenAISettingsFormData {
  endpoint: string;
  apiKey: string;
  apiVersion: string;
  llmDeploymentName: string;
  embeddingDeploymentName: string;
}

// Common Azure OpenAI API versions. Not exhaustive — Azure ships new versions
// regularly, so the combobox also accepts a custom value.
const apiVersionOptions = [
  { value: "2024-10-21", label: "2024-10-21 (GA)" },
  { value: "2024-08-01-preview", label: "2024-08-01-preview" },
  { value: "2024-06-01", label: "2024-06-01" },
  { value: "2024-05-01-preview", label: "2024-05-01-preview" },
  { value: "2024-02-01", label: "2024-02-01" },
  { value: "2023-05-15", label: "2023-05-15" },
];

export function AzureOpenAISettingsForm({
  modelsError,
  isLoadingModels,
}: {
  modelsError?: Error | null;
  isLoadingModels?: boolean;
}) {
  const {
    control,
    register,
    formState: { errors },
  } = useFormContext<AzureOpenAISettingsFormData>();

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <LabelWrapper
          label="Azure OpenAI Endpoint"
          helperText="e.g. https://<resource>.openai.azure.com"
          id="azure-openai-endpoint"
          required
        >
          <Input
            {...register("endpoint", {
              required: "Endpoint URL is required",
            })}
            className={
              errors.endpoint || modelsError ? "!border-destructive" : ""
            }
            id="azure-openai-endpoint"
            type="url"
            placeholder="https://<resource>.openai.azure.com"
          />
        </LabelWrapper>
        {errors.endpoint && (
          <p className="text-sm text-destructive">{errors.endpoint.message}</p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="API Key"
          helperText="Key from your Azure OpenAI resource (Keys and Endpoint)"
          required
          id="azure-openai-api-key"
        >
          <Input
            {...register("apiKey", {
              required: "API key is required",
            })}
            className={
              errors.apiKey || modelsError ? "!border-destructive" : ""
            }
            id="azure-openai-api-key"
            type="password"
            autoComplete="new-password"
            placeholder="your-api-key"
          />
        </LabelWrapper>
        {errors.apiKey && (
          <p className="text-sm text-destructive">{errors.apiKey.message}</p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="API Version"
          helperText="From the deployment's Target URI. Pick a version below or type a custom one."
          required
          id="azure-openai-api-version"
        >
          <Controller
            control={control}
            name="apiVersion"
            rules={{ required: "API version is required" }}
            render={({ field }) => (
              <ModelSelector
                options={apiVersionOptions}
                value={field.value}
                custom
                onValueChange={field.onChange}
                searchPlaceholder="Search or enter a version..."
                noOptionsPlaceholder="No API versions available"
                placeholder="Select API version..."
                hasError={!!errors.apiVersion || !!modelsError}
              />
            )}
          />
        </LabelWrapper>
        {errors.apiVersion && (
          <p className="text-sm text-destructive">
            {errors.apiVersion.message}
          </p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">
            Validating configuration...
          </p>
        )}
        {modelsError && (
          <p className="text-sm text-destructive">
            Connection failed. Check your endpoint, API key, and API version.
          </p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Language model deployment name"
          helperText="The deployment name you set in Azure OpenAI (e.g. gpt-4o)"
          id="azure-openai-llm-deployment"
        >
          <Input
            {...register("llmDeploymentName")}
            id="azure-openai-llm-deployment"
            type="text"
            placeholder="gpt-4o"
          />
        </LabelWrapper>
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Embedding model deployment name"
          helperText="The deployment name you set in Azure OpenAI (e.g. text-embedding-3-large)"
          id="azure-openai-embedding-deployment"
        >
          <Input
            {...register("embeddingDeploymentName")}
            id="azure-openai-embedding-deployment"
            type="text"
            placeholder="text-embedding-3-large"
          />
        </LabelWrapper>
      </div>
      <p className="text-sm text-muted-foreground">
        Enter the deployment name exactly as it appears in Azure OpenAI — not
        the underlying model name.
      </p>
    </div>
  );
}
