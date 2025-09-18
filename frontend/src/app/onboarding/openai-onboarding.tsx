import { useState, useEffect } from "react";
import { LabelInput } from "@/components/label-input";
import OpenAILogo from "@/components/logo/openai-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { useGetOpenAIModelsQuery } from "../api/queries/useGetModelsQuery";
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

  // Fetch models from API
  const { data: modelsData } = useGetOpenAIModelsQuery();

  // Use fetched models or fallback to defaults
  const languageModels = modelsData?.language_models || [{ value: "gpt-4o-mini", label: "gpt-4o-mini", default: true }];
  const embeddingModels = modelsData?.embedding_models || [
    { value: "text-embedding-3-small", label: "text-embedding-3-small", default: true },
  ];

  // Update default selections when models are loaded
  useEffect(() => {
    if (modelsData) {
      const defaultLangModel = modelsData.language_models.find(m => m.default);
      const defaultEmbedModel = modelsData.embedding_models.find(m => m.default);

      if (defaultLangModel && languageModel === "gpt-4o-mini") {
        setLanguageModel(defaultLangModel.value);
      }
      if (defaultEmbedModel && embeddingModel === "text-embedding-3-small") {
        setEmbeddingModel(defaultEmbedModel.value);
      }
    }
  }, [modelsData, languageModel, embeddingModel]);
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
