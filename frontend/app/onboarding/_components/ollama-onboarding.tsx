import type { Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/icons/ollama-logo";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { useGetOllamaModelsQuery } from "../../api/queries/useGetModelsQuery";
import { useModelSelection } from "../_hooks/useModelSelection";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";
import { ModelSelector } from "./model-selector";

export function OllamaOnboarding({
  setSettings,
  sampleDataset,
  setSampleDataset,
  setIsLoadingModels,
  isEmbedding = false,
  alreadyConfigured = false,
  existingEndpoint,
}: {
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
  setIsLoadingModels?: (isLoading: boolean) => void;
  isEmbedding?: boolean;
  alreadyConfigured?: boolean;
  existingEndpoint?: string;
}) {
  const [endpoint, setEndpoint] = useState(
    alreadyConfigured ? undefined : (existingEndpoint || `http://localhost:11434`),
  );
  const [showConnecting, setShowConnecting] = useState(false);
  const debouncedEndpoint = useDebouncedValue(endpoint, 500);

  // Fetch models from API when endpoint is provided (debounced)
  const {
    data: modelsData,
    isLoading: isLoadingModels,
    error: modelsError,
  } = useGetOllamaModelsQuery(
    debouncedEndpoint ? { endpoint: debouncedEndpoint } : undefined,
    { enabled: !!debouncedEndpoint || alreadyConfigured },
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

  // Handle delayed display of connecting state
  useEffect(() => {
    let timeoutId: NodeJS.Timeout;

    if (debouncedEndpoint && isLoadingModels) {
      timeoutId = setTimeout(() => {
        setIsLoadingModels?.(true);
        setShowConnecting(true);
      }, 500);
    } else {
      setShowConnecting(false);
      setIsLoadingModels?.(false);
    }

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    };
  }, [debouncedEndpoint, isLoadingModels, setIsLoadingModels]);

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
            Can't reach Ollama at {debouncedEndpoint}. Update the base URL or
            start the server.
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
