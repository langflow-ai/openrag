import { useState } from "react";
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
  modelProvider,
}: {
  modelProvider: string;
}) {
  const [model, setModel] = useState("");
  const options = [
    { value: "gpt-4", label: "GPT-4" },
    { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
    { value: "gpt-3.5-turbo", label: "GPT-3.5 Turbo" },
    { value: "claude-3-opus", label: "Claude 3 Opus" },
    { value: "claude-3-sonnet", label: "Claude 3 Sonnet" },
  ];
  return (
    <Accordion type="single" collapsible>
      <AccordionItem value="item-1">
        <AccordionTrigger>Advanced settings</AccordionTrigger>
        <AccordionContent className="space-y-6">
          <LabelWrapper
            label="Embedding model"
            description="It’s recommended that you use XYZ, ABC, or DEF models for best performance."
            helperText="The embedding model for your Ollama server."
            id="embedding-model"
            required={true}
          >
            <ModelSelector
              options={options}
              icon={<OllamaLogo className="w-4 h-4" />}
              value={model}
              onValueChange={setModel}
            />
          </LabelWrapper>
          <LabelWrapper
            label="Language model"
            description="It’s recommended that you use XYZ, ABC, or DEF models for best performance."
            helperText="The embedding model for your Ollama server."
            id="embedding-model"
            required={true}
          >
            <ModelSelector
              options={options}
              icon={<OllamaLogo className="w-4 h-4" />}
              value={model}
              onValueChange={setModel}
            />
          </LabelWrapper>
          <Separator />
          <LabelWrapper
            label="Sample dataset"
            description="Ingest two small PDFs"
            id="sample-dataset"
            flex
          >
            <Switch />
          </LabelWrapper>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
