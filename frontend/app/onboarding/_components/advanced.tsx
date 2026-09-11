import { LabelWrapper } from "@/components/label-wrapper";
import { ModelSelector } from "@/components/models/model-selector";

export function AdvancedOnboarding({
  icon,
  languageModels,
  embeddingModels,
  languageModel,
  embeddingModel,
  setLanguageModel,
  setEmbeddingModel,
}: {
  icon?: React.ReactNode;
  languageModels?: { value: string; label: string }[];
  embeddingModels?: { value: string; label: string }[];
  languageModel?: string;
  embeddingModel?: string;
  setLanguageModel?: (model: string) => void;
  setEmbeddingModel?: (model: string) => void;
}) {
  const hasEmbeddingModels =
    embeddingModels !== undefined &&
    embeddingModel !== undefined &&
    setEmbeddingModel !== undefined;
  const hasLanguageModels =
    languageModels !== undefined &&
    languageModel !== undefined &&
    setLanguageModel !== undefined;

  return (
    <div className="space-y-6">
      {hasEmbeddingModels && (
        <LabelWrapper
          label="Embedding model"
          helperText="Model used for knowledge ingest and retrieval"
          id="embedding-model"
          required={true}
        >
          <ModelSelector
            options={embeddingModels}
            custom
            data-testid="embedding-model-selector"
            icon={icon}
            value={embeddingModel}
            onValueChange={setEmbeddingModel}
          />
        </LabelWrapper>
      )}
      {hasLanguageModels && (
        <LabelWrapper
          label="Language model"
          helperText="Model used for chat"
          id="embedding-model"
          required={true}
        >
          <ModelSelector
            options={languageModels}
            custom
            data-testid="language-model-selector"
            icon={icon}
            value={languageModel}
            onValueChange={setLanguageModel}
          />
        </LabelWrapper>
      )}
    </div>
  );
}
