import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import OllamaLogo from "@/components/icons/ollama-logo";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import { ModelSelector } from "@/components/models/model-selector";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOllamaModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../_hooks/useModelSelection";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";

export function OllamaOnboarding({
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
    alreadyConfigured
      ? undefined
      : existingEndpoint || `http://localhost:11434`,
  );
  const [connectingVisibleAfterDelay, setConnectingVisibleAfterDelay] =
    useState(false);
  const debouncedEndpoint = useDebouncedValue(endpoint, 500);

  // Fetch models from API when endpoint is provided (debounced)
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOllamaModelsQuery(
    debouncedEndpoint ? { endpoint: debouncedEndpoint } : undefined,
    { enabled: !!debouncedEndpoint || alreadyConfigured || alreadyConfigured },
  );

  // Use custom hook for model selection logic
  const {
    languageModel,
    embeddingModel,
    setLanguageModel,
    setEmbeddingModel,
    languageModels,
    embeddingModels,
  } = useModelSelection(modelsData, isEmbedding);

  const isConnecting = !!debouncedEndpoint && isLoadingModels;

  // Delay "connecting" message to avoid flicker on short fetches.
  // Visibility is derived from isConnecting so we don't sync false via an effect.
  useEffect(() => {
    if (!isConnecting) {
      return;
    }
    const timeoutId = setTimeout(() => {
      setConnectingVisibleAfterDelay(true);
    }, 500);
    return () => {
      clearTimeout(timeoutId);
      setConnectingVisibleAfterDelay(false);
    };
  }, [isConnecting]);

  const showConnecting = isConnecting && connectingVisibleAfterDelay;

  // Update settings when values change
  useUpdateSettings(
    "ollama",
    {
      endpoint,
      languageModel,
      embeddingModel,
    },
    setSettings,
    isEmbedding,
  );

  // Check validation state based on models query
  const hasConnectionError = debouncedEndpoint && modelsError;
  const hasNoModels =
    modelsData &&
    !modelsData.language_models?.length &&
    !modelsData.embedding_models?.length;

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <LabelInput
          label="Ollama Base URL"
          helperText="Base URL of your Ollama server"
          id="api-endpoint"
          required
          placeholder={
            alreadyConfigured
              ? "http://••••••••••••••••••••"
              : "http://localhost:11434"
          }
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
          disabled={alreadyConfigured}
        />
        {alreadyConfigured && (
          <p className="text-mmd text-muted-foreground">
            Reusing endpoint from model provider selection.
          </p>
        )}
        {showConnecting && (
          <p className="text-mmd text-muted-foreground">
            Connecting to Ollama server...
          </p>
        )}
        {hasConnectionError && (
          <p className="text-mmd text-accent-amber-foreground">
            {modelsError.message}
          </p>
        )}
        {hasNoModels && (
          <p className="text-mmd text-accent-amber-foreground">
            No models found. Install embedding and agent models on your Ollama
            server.
          </p>
        )}
      </div>
      {isEmbedding && setEmbeddingModel && (
        <LabelWrapper
          label="Embedding model"
          helperText="Model used for knowledge ingest and retrieval"
          id="embedding-model"
          required={true}
        >
          <ModelSelector
            options={embeddingModels}
            data-testid="embedding-model-selector"
            icon={<OllamaLogo className="w-4 h-4" />}
            noOptionsPlaceholder={
              isLoadingModels
                ? "Loading models..."
                : "No embedding models detected. Install an embedding model to continue."
            }
            value={embeddingModel}
            onValueChange={setEmbeddingModel}
          />
        </LabelWrapper>
      )}
      {!isEmbedding && setLanguageModel && (
        <LabelWrapper
          label="Language model"
          helperText="Model used for chat"
          id="embedding-model"
          required={true}
        >
          <ModelSelector
            options={languageModels}
            data-testid="language-model-selector"
            icon={<OllamaLogo className="w-4 h-4" />}
            noOptionsPlaceholder={
              isLoadingModels
                ? "Loading models..."
                : "No language models detected. Install a language model to continue."
            }
            value={languageModel}
            onValueChange={setLanguageModel}
          />
        </LabelWrapper>
      )}
    </div>
  );
}
