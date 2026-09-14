import { Controller, useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { ModelSelector } from "@/components/models/model-selector";
import { Input } from "@/components/ui/input";

export interface WatsonxSettingsFormData {
  endpoint: string;
  apiKey: string;
  projectId: string;
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
  } = useFormContext<WatsonxSettingsFormData>();

  return (
    <div className="min-w-0 space-y-4">
      <div className="min-w-0 space-y-2">
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
          <p className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]">
            {errors.endpoint.message}
          </p>
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
          <p className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]">
            {errors.projectId.message}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="watsonx API key"
          helperText="API key to access watsonx.ai"
          required
          id="api-key"
        >
          <Input
            {...register("apiKey", {
              required: "API key is required",
            })}
            className={
              errors.apiKey || modelsError ? "!border-destructive" : ""
            }
            id="api-key"
            type="password"
            autoComplete="new-password"
            placeholder="your-api-key"
          />
        </LabelWrapper>
        {errors.apiKey && (
          <p className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]">
            {errors.apiKey.message}
          </p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">
            Validating configuration...
          </p>
        )}
        {modelsError && (
          <p
            data-testid="provider-connection-error"
            className="text-sm text-destructive min-w-0 [overflow-wrap:anywhere]"
          >
            {modelsError.message}
          </p>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Configure language and embedding models in the Settings page after
        saving your credentials.
      </p>
    </div>
  );
}
