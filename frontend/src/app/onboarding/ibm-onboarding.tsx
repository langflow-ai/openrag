import { useState, useEffect } from "react";
import { LabelInput } from "@/components/label-input";
import IBMLogo from "@/components/logo/ibm-logo";
import type { Settings } from "../api/queries/useGetSettingsQuery";
import { useGetIBMModelsQuery } from "../api/queries/useGetModelsQuery";
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
  const [endpoint, setEndpoint] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [projectId, setProjectId] = useState("");
  const [languageModel, setLanguageModel] = useState("meta-llama/llama-3-1-70b-instruct");
  const [embeddingModel, setEmbeddingModel] = useState("ibm/slate-125m-english-rtrvr");

  // Fetch models from API when all credentials are provided
  const { data: modelsData } = useGetIBMModelsQuery(
    (apiKey && endpoint && projectId) ? { api_key: apiKey, endpoint, project_id: projectId } : undefined,
    { enabled: !!(apiKey && endpoint && projectId) }
  );

  // Use fetched models or fallback to defaults
  const languageModels = modelsData?.language_models || [
    { value: "meta-llama/llama-3-1-70b-instruct", label: "Llama 3.1 70B Instruct", default: true },
    { value: "meta-llama/llama-3-1-8b-instruct", label: "Llama 3.1 8B Instruct" },
    { value: "ibm/granite-13b-chat-v2", label: "Granite 13B Chat v2" },
    { value: "ibm/granite-13b-instruct-v2", label: "Granite 13B Instruct v2" },
  ];
  const embeddingModels = modelsData?.embedding_models || [
    { value: "ibm/slate-125m-english-rtrvr", label: "Slate 125M English Retriever", default: true },
    { value: "sentence-transformers/all-minilm-l12-v2", label: "All-MiniLM L12 v2" },
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
        placeholder="https://us-south.ml.cloud.ibm.com"
        value={endpoint}
        onChange={(e) => setEndpoint(e.target.value)}
      />
      <LabelInput
        label="IBM API key"
        helperText="The API key for your watsonx.ai account."
        id="api-key"
        required
        placeholder="your-api-key"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
      />
      <LabelInput
        label="IBM Project ID"
        helperText="The project ID for your watsonx.ai account."
        id="project-id"
        required
        placeholder="your-project-id"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
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
