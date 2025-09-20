import { useState, useEffect } from "react";
import type { ModelsResponse } from "../../api/queries/useGetModelsQuery";

export function useModelSelection(modelsData: ModelsResponse | undefined) {
  const [languageModel, setLanguageModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");

  // Update default selections when models are loaded
  useEffect(() => {
    if (modelsData) {
      const defaultLangModel = modelsData.language_models.find(
        (m) => m.default,
      );
      const defaultEmbedModel = modelsData.embedding_models.find(
        (m) => m.default,
      );

      // Set language model: prefer default, fallback to first available
      if (!languageModel) {
        if (defaultLangModel) {
          setLanguageModel(defaultLangModel.value);
        } else if (modelsData.language_models.length > 0) {
          setLanguageModel(modelsData.language_models[0].value);
        }
      }

      // Set embedding model: prefer default, fallback to first available
      if (!embeddingModel) {
        if (defaultEmbedModel) {
          setEmbeddingModel(defaultEmbedModel.value);
        } else if (modelsData.embedding_models.length > 0) {
          setEmbeddingModel(modelsData.embedding_models[0].value);
        }
      }
    }
  }, [modelsData, languageModel, embeddingModel]);

  return {
    languageModel,
    embeddingModel,
    setLanguageModel,
    setEmbeddingModel,
    languageModels: modelsData?.language_models || [],
    embeddingModels: modelsData?.embedding_models || [],
  };
}
