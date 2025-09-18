import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";
import { ModelSelector } from "./model-selector";

export function OllamaOnboarding({
  settings,
  setSettings,
  sampleDataset,
  setSampleDataset,
}: {
  settings: Settings;
  setSettings: (settings: Settings) => void;
  sampleDataset: boolean;
  setSampleDataset: (dataset: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [languageModel, setLanguageModel] = useState("gpt-oss");
  const [embeddingModel, setEmbeddingModel] = useState(
    "text-embedding-3-small",
  );
  const languageModels = [
    { value: "gpt-oss", label: "gpt-oss", default: true },
    { value: "llama3.1", label: "llama3.1" },
    { value: "llama3.2", label: "llama3.2" },
    { value: "llama3.3", label: "llama3.3" },
    { value: "llama3.4", label: "llama3.4" },
    { value: "llama3.5", label: "llama3.5" },
  ];
  const embeddingModels = [
    { value: "text-embedding-3-small", label: "text-embedding-3-small" },
  ];

  const handleSampleDatasetChange = (dataset: boolean) => {
    setSampleDataset(dataset);
  };
  return (
    <>
      <LabelInput
        label="Ollama Endpoint"
        helperText="The endpoint for your Ollama server."
        id="api-endpoint"
        required
        placeholder="http://..."
      />
      <LabelWrapper
        label="Embedding model"
        helperText="The embedding model for your Ollama server."
        id="embedding-model"
        required={true}
      >
        <ModelSelector
          options={embeddingModels}
          icon={<OllamaLogo className="w-4 h-4" />}
          value={embeddingModel}
          onValueChange={setEmbeddingModel}
        />
      </LabelWrapper>
      <LabelWrapper
        label="Language model"
        helperText="The embedding model for your Ollama server."
        id="embedding-model"
        required={true}
      >
        <ModelSelector
          options={languageModels}
          icon={<OllamaLogo className="w-4 h-4" />}
          value={languageModel}
          onValueChange={setLanguageModel}
        />
      </LabelWrapper>

      <AdvancedOnboarding
        sampleDataset={sampleDataset}
        setSampleDataset={handleSampleDatasetChange}
      />
    </>
  );
}
