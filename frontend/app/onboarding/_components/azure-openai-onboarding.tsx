import type { Dispatch, SetStateAction } from "react";
import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetAzureOpenAIModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";

export function AzureOpenAIOnboarding({
  setSettings,
  isEmbedding = false,
  alreadyConfigured = false,
  existingEndpoint,
  existingApiVersion,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  alreadyConfigured?: boolean;
  existingEndpoint?: string;
  existingApiVersion?: string;
}) {
  const [endpoint, setEndpoint] = useState(
    alreadyConfigured ? "" : existingEndpoint || "",
  );
  const [apiKey, setApiKey] = useState("");
  const [apiVersion, setApiVersion] = useState(
    alreadyConfigured ? "" : existingApiVersion || "",
  );
  const [deploymentName, setDeploymentName] = useState("");

  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedApiKey = useDebouncedValue(apiKey, 500);
  const debouncedApiVersion = useDebouncedValue(apiVersion, 500);

  const {
    isLoading: isLoadingModels,
    isFetching: isFetchingModels,
    error: modelsError,
  } = useGetAzureOpenAIModelsQuery(
    {
      endpoint: alreadyConfigured ? existingEndpoint : debouncedEndpoint,
      apiKey: alreadyConfigured ? undefined : debouncedApiKey,
      apiVersion: alreadyConfigured ? existingApiVersion : debouncedApiVersion,
    },
    {
      enabled: alreadyConfigured
        ? !!existingEndpoint && !!existingApiVersion
        : !!debouncedEndpoint && !!debouncedApiKey && !!debouncedApiVersion,
    },
  );

  const showModelsError =
    !!modelsError && !isLoadingModels && !isFetchingModels;

  useUpdateSettings(
    "azure_openai",
    {
      endpoint: alreadyConfigured ? existingEndpoint : endpoint,
      apiKey: alreadyConfigured ? undefined : apiKey,
      apiVersion: alreadyConfigured ? existingApiVersion : apiVersion,
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
          label="Azure OpenAI endpoint"
          helperText="e.g. https://<resource>.openai.azure.com"
          id="azure-openai-endpoint"
          required
          placeholder="https://<resource>.openai.azure.com"
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
        <>
          <div className="space-y-1">
            <LabelInput
              label="API key"
              helperText="Key from your Azure OpenAI resource (Keys and Endpoint)"
              className={showModelsError ? "!border-destructive" : ""}
              id="azure-openai-api-key"
              type="password"
              required
              placeholder="your-api-key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <LabelInput
              label="API version"
              helperText="e.g. 2024-10-21 (from the deployment's Target URI)"
              className={showModelsError ? "!border-destructive" : ""}
              id="azure-openai-api-version"
              required
              placeholder="2024-10-21"
              value={apiVersion}
              onChange={(e) => setApiVersion(e.target.value)}
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
        </>
      )}
      <div className="space-y-1">
        <LabelInput
          label={
            isEmbedding
              ? "Embedding model deployment name"
              : "Language model deployment name"
          }
          helperText="The deployment name exactly as it appears in Azure OpenAI, not the underlying model name"
          id="azure-openai-deployment"
          required
          placeholder={isEmbedding ? "text-embedding-3-large" : "gpt-4o"}
          value={deploymentName}
          onChange={(e) => setDeploymentName(e.target.value)}
        />
      </div>
    </div>
  );
}
