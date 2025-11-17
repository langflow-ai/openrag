import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";

export interface OpenAISettingsFormData {
  apiKey: string;
}

export function OpenAISettingsForm({
  modelsError,
  isLoadingModels,
}: {
  modelsError?: Error | null;
  isLoadingModels?: boolean;
}) {
  const {
    register,
    formState: { errors },
  } = useFormContext<OpenAISettingsFormData>();

  const apiKeyError = modelsError
    ? "Invalid OpenAI API key. Verify or replace the key."
    : errors.apiKey?.message;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <LabelWrapper
          label="OpenAI API key"
          helperText="The API key for your OpenAI account"
          required
          id="api-key"
        >
          <Input
            {...register("apiKey", {
              required: "API key is required",
            })}
            className={apiKeyError ? "!border-destructive" : ""}
            id="api-key"
            type="password"
            placeholder="sk-..."
          />
        </LabelWrapper>
        {apiKeyError && (
          <p className="text-sm text-destructive">{apiKeyError}</p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">Validating API key...</p>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Configure language and embedding models in the Settings page after
        saving your API key.
      </p>
    </div>
  );
}
