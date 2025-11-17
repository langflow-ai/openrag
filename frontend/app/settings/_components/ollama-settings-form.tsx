import { useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";

export interface OllamaSettingsFormData {
  endpoint: string;
}

export function OllamaSettingsForm({
  modelsError,
  isLoadingModels,
}: {
  modelsError?: Error | null;
  isLoadingModels?: boolean;
}) {
  const {
    register,
    formState: { errors },
  } = useFormContext<OllamaSettingsFormData>();

  const endpointError = modelsError
    ? "Connection failed. Check your Ollama server URL."
    : errors.endpoint?.message;

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
            className={endpointError ? "!border-destructive" : ""}
            id="endpoint"
            type="text"
            placeholder="http://localhost:11434"
          />
        </LabelWrapper>
        {endpointError && (
          <p className="text-sm text-destructive">{endpointError}</p>
        )}
        {isLoadingModels && (
          <p className="text-sm text-muted-foreground">
            Validating connection...
          </p>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Configure language and embedding models in the Settings page after
        saving your endpoint.
      </p>
    </div>
  );
}
