import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { ModelSelector } from "./model-selector";

export function AdvancedOnboarding({
  icon,
  languageModels,
  embeddingModels,
  languageModel,
  embeddingModel,
  setLanguageModel,
  setEmbeddingModel,
  sampleDataset,
  setSampleDataset,
}: {
  icon?: React.ReactNode;
  languageModels?: { value: string; label: string }[];
  embeddingModels?: { value: string; label: string }[];
  languageModel?: string;
  embeddingModel?: string;
  setLanguageModel?: (model: string) => void;
  setEmbeddingModel?: (model: string) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const hasEmbeddingModels =
    embeddingModels && embeddingModel && setEmbeddingModel;
  const hasLanguageModels = languageModels && languageModel && setLanguageModel;
  return (
    <Accordion type="single" collapsible>
      <AccordionItem value="item-1">
        <AccordionTrigger>Advanced settings</AccordionTrigger>
        <AccordionContent className="space-y-6">
          {hasEmbeddingModels && (
            <LabelWrapper
              label="Embedding model"
              description="It’s recommended that you use XYZ, ABC, or DEF models for best performance."
              helperText="The embedding model for your Ollama server."
              id="embedding-model"
              required={true}
            >
              <ModelSelector
                options={embeddingModels}
                icon={icon}
                value={embeddingModel}
                onValueChange={setEmbeddingModel}
              />
            </LabelWrapper>
          )}
          {hasLanguageModels && (
            <LabelWrapper
              label="Language model"
              description="It’s recommended that you use XYZ, ABC, or DEF models for best performance."
              helperText="The embedding model for your Ollama server."
              id="embedding-model"
              required={true}
            >
              <ModelSelector
                options={languageModels}
                icon={icon}
                value={languageModel}
                onValueChange={setLanguageModel}
              />
            </LabelWrapper>
          )}
          {(hasLanguageModels || hasEmbeddingModels) && <Separator />}
          <LabelWrapper
            label="Sample dataset"
            description="Ingest two small PDFs"
            id="sample-dataset"
            flex
          >
            <Switch
              checked={sampleDataset}
              onCheckedChange={setSampleDataset}
            />
          </LabelWrapper>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
