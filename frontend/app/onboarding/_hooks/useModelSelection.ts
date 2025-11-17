import { useEffect, useState } from "react";
import type { ModelsResponse } from "../../api/queries/useGetModelsQuery";

export function useModelSelection(
  modelsData: ModelsResponse | undefined,
  isEmbedding: boolean,
) {
  const [languageModel, setLanguageModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");

  // Update default selections when models are loaded
  useEffect(() => {
    if (modelsData) {
      const defaultLangModel = isEmbedding
        ? undefined
        : modelsData.language_models.find((m) => m.default);
      const defaultEmbedModel = isEmbedding
        ? modelsData.embedding_models.find((m) => m.default)
        : undefined;

      // Set language model: prefer default, fallback to first available
      if (!languageModel && !isEmbedding) {
        if (defaultLangModel) {
          setLanguageModel(defaultLangModel.value);
        } else if (modelsData.language_models.length > 0) {
          setLanguageModel(modelsData.language_models[0].value);
        }
      }

      // Set embedding model: prefer default, fallback to first available
      if (!embeddingModel && isEmbedding) {
        if (defaultEmbedModel) {
          setEmbeddingModel(defaultEmbedModel.value);
        } else if (modelsData.embedding_models.length > 0) {
          setEmbeddingModel(modelsData.embedding_models[0].value);
        }
      }
    }
  }, [modelsData, languageModel, embeddingModel, isEmbedding]);

  return {
    languageModel,
    embeddingModel,
    setLanguageModel: !isEmbedding ? setLanguageModel : undefined,
    setEmbeddingModel: isEmbedding ? setEmbeddingModel : undefined,
    languageModels: modelsData?.language_models || [],
    embeddingModels: modelsData?.embedding_models || [],
  };
}
