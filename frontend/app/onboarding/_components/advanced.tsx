import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { ModelSelector } from "./model-selector";

export function AdvancedOnboarding({
  icon,
  languageModels,
  embeddingModels,
  languageModel,
  embeddingModel,
  setLanguageModel,
  setEmbeddingModel,
  baseUrl,
  onBaseUrlChange,
  baseUrlDisabled,
}: {
  icon?: React.ReactNode;
  languageModels?: { value: string; label: string }[];
  embeddingModels?: { value: string; label: string }[];
  languageModel?: string;
  embeddingModel?: string;
  setLanguageModel?: (model: string) => void;
  setEmbeddingModel?: (model: string) => void;
  /** Optional custom base URL input (currently OpenAI-only). */
  baseUrl?: string;
  onBaseUrlChange?: (value: string) => void;
  baseUrlDisabled?: boolean;
}) {
  const hasEmbeddingModels =
    embeddingModels !== undefined &&
    embeddingModel !== undefined &&
    setEmbeddingModel !== undefined;
  const hasLanguageModels =
    languageModels !== undefined &&
    languageModel !== undefined &&
    setLanguageModel !== undefined;
  const hasBaseUrl = baseUrl !== undefined && onBaseUrlChange !== undefined;

  return (
    <Accordion type="single" collapsible>
      <AccordionItem value="item-1">
        <AccordionTrigger data-testid="advanced-settings-button">
          Advanced settings
        </AccordionTrigger>
        <AccordionContent className="space-y-6">
          {hasBaseUrl && (
            <LabelInput
              label="Base URL"
              helperText="Optional: point to a self-hosted OpenAI-compatible gateway instead of api.openai.com"
              id="base-url"
              required={false}
              placeholder="https://api.openai.com/v1"
              value={baseUrl}
              onChange={(e) => onBaseUrlChange?.(e.target.value)}
              disabled={baseUrlDisabled}
            />
          )}
          {hasEmbeddingModels && (
            <LabelWrapper
              label="Embedding model"
              helperText="Model used for knowledge ingest and retrieval"
              id="embedding-model"
              required={true}
            >
              <ModelSelector
                options={embeddingModels}
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
                data-testid="language-model-selector"
                icon={icon}
                value={languageModel}
                onValueChange={setLanguageModel}
              />
            </LabelWrapper>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
