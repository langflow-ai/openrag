import { useState, useEffect } from "react";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import OllamaLogo from "@/components/logo/ollama-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { useGetOllamaModelsQuery } from "../api/queries/useGetModelsQuery";
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
  const [endpoint, setEndpoint] = useState("");
  const [languageModel, setLanguageModel] = useState("llama3.2");
  const [embeddingModel, setEmbeddingModel] = useState("nomic-embed-text");

  // Fetch models from API when endpoint is provided
  const { data: modelsData } = useGetOllamaModelsQuery(
    endpoint ? { endpoint } : undefined,
    { enabled: !!endpoint }
  );

  // Use fetched models or fallback to defaults
  const languageModels = modelsData?.language_models || [
    { value: "llama3.2", label: "llama3.2", default: true },
    { value: "llama3.1", label: "llama3.1" },
    { value: "llama3", label: "llama3" },
    { value: "mistral", label: "mistral" },
    { value: "codellama", label: "codellama" },
  ];
  const embeddingModels = modelsData?.embedding_models || [
    { value: "nomic-embed-text", label: "nomic-embed-text", default: true },
  ];

  // Update default selections when models are loaded
  useEffect(() => {
    if (modelsData) {
      const defaultLangModel = modelsData.language_models.find(m => m.default);
      const defaultEmbedModel = modelsData.embedding_models.find(m => m.default);

      if (defaultLangModel) {
        setLanguageModel(defaultLangModel.value);
      }
      if (defaultEmbedModel) {
        setEmbeddingModel(defaultEmbedModel.value);
      }
    }
  }, [modelsData]);

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
        placeholder="http://localhost:11434"
        value={endpoint}
        onChange={(e) => setEndpoint(e.target.value)}
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
