import { Controller, useFormContext } from "react-hook-form";
import { ModelSelector } from "@/app/onboarding/_components/model-selector";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";

export interface AzureAIFoundrySettingsFormData {
  endpoint: string;
  apiKey: string;
  apiVersion: string;
  llmDeploymentName: string;
  embeddingDeploymentName: string;
}

// Per Microsoft's Azure AI Model Inference REST API reference, which uses
// this value in every example request (chat completions and embeddings):
// https://learn.microsoft.com/en-us/rest/api/aifoundry/modelinference/
// Left blank, the backend applies this same default — the field is only
// exposed so it can be overridden for a resource pinned to an older version.
// The combobox also accepts an arbitrary custom value.
const apiVersionOptions = [{ value: "2025-04-01", label: "2025-04-01" }];

export function AzureAIFoundrySettingsForm({
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
  } = useFormContext<AzureAIFoundrySettingsFormData>();

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <LabelWrapper
          label="Azure AI Foundry Endpoint"
          helperText="e.g. https://<resource>.services.ai.azure.com/models"
          id="azure-endpoint"
          required
        >
          <Input
            {...register("endpoint", {
              required: "Endpoint URL is required",
            })}
            className={
              errors.endpoint || modelsError ? "!border-destructive" : ""
            }
            id="azure-endpoint"
            type="url"
            placeholder="https://<resource>.services.ai.azure.com/models"
          />
        </LabelWrapper>
        {errors.endpoint && (
          <p className="text-sm text-destructive">{errors.endpoint.message}</p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="API Key"
          helperText="API key from your Azure AI Foundry project"
          required
          id="azure-api-key"
        >
          <Input
            {...register("apiKey", {
              required: "API key is required",
            })}
            className={
              errors.apiKey || modelsError ? "!border-destructive" : ""
            }
            id="azure-api-key"
            type="password"
            autoComplete="new-password"
            placeholder="your-api-key"
          />
        </LabelWrapper>
        {errors.apiKey && (
          <p className="text-sm text-destructive">{errors.apiKey.message}</p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">
            Validating configuration...
          </p>
        )}
        {modelsError && (
          <p className="text-sm text-destructive">
            Connection failed. Check your endpoint URL and API key.
          </p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="API Version"
          helperText="Azure requires one on every request. Defaults to 2025-04-01 if left blank — only override this for a resource pinned to a different version."
          id="azure-api-version"
        >
          <Controller
            control={control}
            name="apiVersion"
            render={({ field }) => (
              <ModelSelector
                options={apiVersionOptions}
                value={field.value}
                custom
                onValueChange={field.onChange}
                searchPlaceholder="Search or enter a version..."
                noOptionsPlaceholder="No API versions available"
                placeholder="2025-04-01 (default)"
              />
            )}
          />
        </LabelWrapper>
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Language model deployment name"
          helperText="The deployment name you set in Azure AI Foundry (e.g. Phi-4-mini-instruct)"
          id="azure-llm-deployment"
        >
          <Input
            {...register("llmDeploymentName")}
            id="azure-llm-deployment"
            type="text"
            placeholder="Phi-4-mini-instruct"
          />
        </LabelWrapper>
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Embedding model deployment name"
          helperText="The deployment name you set in Azure AI Foundry (e.g. Cohere-embed-v3-english)"
          id="azure-embedding-deployment"
        >
          <Input
            {...register("embeddingDeploymentName")}
            id="azure-embedding-deployment"
            type="text"
            placeholder="Cohere-embed-v3-english"
          />
        </LabelWrapper>
      </div>
      <p className="text-sm text-muted-foreground">
        Enter the deployment name exactly as it appears in Azure AI Foundry —
        not the underlying model name.
      </p>
    </div>
  );
}
