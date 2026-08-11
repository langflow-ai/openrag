import type { Dispatch, SetStateAction } from "react";
import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetAzureAIFoundryModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";

export function AzureAIFoundryOnboarding({
  setSettings,
  isEmbedding = false,
  alreadyConfigured = false,
  existingEndpoint,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  alreadyConfigured?: boolean;
  existingEndpoint?: string;
}) {
  const [endpoint, setEndpoint] = useState(
    alreadyConfigured ? "" : existingEndpoint || "",
  );
  const [apiKey, setApiKey] = useState("");
  const [deploymentName, setDeploymentName] = useState("");

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);

  const {
    isLoading: isLoadingModels,
    isFetching: isFetchingModels,
    error: modelsError,
  } = useGetAzureAIFoundryModelsQuery(
    {
      endpoint: alreadyConfigured ? existingEndpoint : debouncedEndpoint,
      apiKey: alreadyConfigured ? undefined : debouncedApiKey,
    },
    {
      enabled: alreadyConfigured
        ? !!existingEndpoint
        : !!debouncedEndpoint && !!debouncedApiKey,
    },
  );

  const showModelsError =
    !!modelsError && !isLoadingModels && !isFetchingModels;

  useUpdateSettings(
    "azure_ai_foundry",
    {
      endpoint: alreadyConfigured ? existingEndpoint : endpoint,
      apiKey: alreadyConfigured ? undefined : apiKey,
      languageModel: !isEmbedding ? deploymentName : undefined,
      embeddingModel: isEmbedding ? deploymentName : undefined,
    },
    setSettings,
    isEmbedding,
  );

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <LabelInput
          label="Azure AI Foundry endpoint"
          helperText="e.g. https://<resource>.services.ai.azure.com/models"
          id="azure-ai-foundry-endpoint"
          required
          placeholder="https://<resource>.services.ai.azure.com/models"
          value={alreadyConfigured ? existingEndpoint || "" : endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
          disabled={alreadyConfigured}
        />
        {alreadyConfigured && (
          <p className="text-mmd text-muted-foreground">
            Reusing endpoint from model provider selection.
          </p>
        )}
      </div>
      {!alreadyConfigured && (
        <div className="space-y-1">
          <LabelInput
            label="API key"
            helperText="API key from your Azure AI Foundry project"
            className={showModelsError ? "!border-destructive" : ""}
            id="azure-ai-foundry-api-key"
            type="password"
            required
            placeholder="your-api-key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          {(isLoadingModels || isFetchingModels) && (
            <p className="text-mmd text-muted-foreground">
              Validating configuration...
            </p>
          )}
          {showModelsError && (
            <p className="text-mmd text-destructive">{modelsError.message}</p>
          )}
        </div>
      )}
      <div className="space-y-1">
        <LabelInput
          label={
            isEmbedding
              ? "Embedding model deployment name"
              : "Language model deployment name"
          }
          helperText="The deployment name exactly as it appears in Azure AI Foundry, not the underlying model name"
          id="azure-ai-foundry-deployment"
          required
          placeholder={
            isEmbedding ? "Cohere-embed-v3-english" : "Phi-4-mini-instruct"
          }
          value={deploymentName}
          onChange={(e) => setDeploymentName(e.target.value)}
        />
      </div>
    </div>
  );
}
