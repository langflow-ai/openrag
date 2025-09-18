import { useState } from "react";
import { LabelInput } from "@/components/label-input";
import IBMLogo from "@/components/logo/ibm-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { AdvancedOnboarding } from "./advanced";

export function IBMOnboarding({
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
  const languageModels = [
    { value: "gpt-oss", label: "gpt-oss" },
    { value: "llama3.1", label: "llama3.1" },
    { value: "llama3.2", label: "llama3.2" },
    { value: "llama3.3", label: "llama3.3" },
    { value: "llama3.4", label: "llama3.4" },
    { value: "llama3.5", label: "llama3.5" },
  ];
  const embeddingModels = [
    { value: "text-embedding-3-small", label: "text-embedding-3-small" },
  ];
  const [languageModel, setLanguageModel] = useState("gpt-oss");
  const [embeddingModel, setEmbeddingModel] = useState(
    "text-embedding-3-small",
  );
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
        label="watsonx.ai API Endpoint"
        helperText="The API endpoint for your watsonx.ai account."
        id="api-endpoint"
        required
        placeholder="https://..."
      />
      <LabelInput
        label="IBM API key"
        helperText="The API key for your watsonx.ai account."
        id="api-key"
        required
        placeholder="sk-..."
      />
      <LabelInput
        label="IBM Project ID"
        helperText="The project ID for your watsonx.ai account."
        id="project-id"
        required
        placeholder="..."
      />
      <AdvancedOnboarding
        icon={<IBMLogo className="w-4 h-4" />}
        languageModels={languageModels}
        embeddingModels={embeddingModels}
        languageModel={languageModel}
        embeddingModel={embeddingModel}
        sampleDataset={sampleDataset}
        setLanguageModel={handleLanguageModelChange}
        setEmbeddingModel={handleEmbeddingModelChange}
        setSampleDataset={handleSampleDatasetChange}
      />
    </>
  );
}
