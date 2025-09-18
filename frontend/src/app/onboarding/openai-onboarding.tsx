import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import OpenAILogo from "@/components/logo/openai-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";

export function OpenAIOnboarding({
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
  const [languageModel, setLanguageModel] = useState("gpt-4o-mini");
  const [embeddingModel, setEmbeddingModel] = useState(
    "text-embedding-3-small",
  );
  const languageModels = [{ value: "gpt-4o-mini", label: "gpt-4o-mini" }];
  const embeddingModels = [
    { value: "text-embedding-3-small", label: "text-embedding-3-small" },
  ];
  const handleLanguageModelChange = (model: string) => {
    setLanguageModel(model);
  };

  const handleEmbeddingModelChange = (model: string) => {
    setEmbeddingModel(model);
  };

  const handleSampleDatasetChange = (dataset: boolean) => {
    setSampleDataset(dataset);
  };
  return (
    <>
      <LabelInput
        label="OpenAI API key"
        helperText="The API key for your OpenAI account."
        id="api-key"
        required
        placeholder="sk-..."
      />
      <AdvancedOnboarding
        icon={<OpenAILogo className="w-4 h-4" />}
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        languageModel={languageModel}
        embeddingModel={embeddingModel}
        sampleDataset={sampleDataset}
        setLanguageModel={handleLanguageModelChange}
        setSampleDataset={handleSampleDatasetChange}
        setEmbeddingModel={handleEmbeddingModelChange}
      />
    </>
  );
}
