import { useFormContext, Controller } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import { ModelSelector } from "@/app/onboarding/components/model-selector";

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
            Connection failed. Check your configuration.
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
