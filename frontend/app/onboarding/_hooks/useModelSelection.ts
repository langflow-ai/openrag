import { useState } from "react";
import type { ModelsResponse } from "../../api/queries/useGetModelsQuery";

export function useModelSelection(
  modelsData: ModelsResponse | undefined,
  isEmbedding: boolean,
) {
  const [languageModel, setLanguageModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");

  // Set default selections when models first load (render-time adjustment)
  const [prevModelsData, setPrevModelsData] = useState<
    ModelsResponse | undefined
  >();
  if (modelsData !== prevModelsData) {
    setPrevModelsData(modelsData);
    if (modelsData) {
      if (!isEmbedding) {
        if (!languageModel) {
          const defaultLangModel = modelsData.language_models.find(
            (m) => m.default,
          );
          if (defaultLangModel) {
            setLanguageModel(defaultLangModel.value);
          } else if (modelsData.language_models.length > 0) {
            setLanguageModel(modelsData.language_models[0].value);
          }
        } else if (
          modelsData.language_models.length > 0 &&
          !modelsData.language_models.some((m) => m.value === languageModel)
        ) {
          // The list just changed underneath the current pick (a new API
          // key, a provider swap) and it's no longer offered. Clear it here,
          // at the point the list itself changes, rather than reactively in
          // ModelSelector. An empty list is left alone — that's more likely
          // a transient load than an intentional "nothing is valid anymore".
          setLanguageModel("");
        }
      }

      if (isEmbedding) {
        if (!embeddingModel) {
          const defaultEmbedModel = modelsData.embedding_models.find(
            (m) => m.default,
          );
          if (defaultEmbedModel) {
            setEmbeddingModel(defaultEmbedModel.value);
          } else if (modelsData.embedding_models.length > 0) {
            setEmbeddingModel(modelsData.embedding_models[0].value);
          }
        } else if (
          modelsData.embedding_models.length > 0 &&
          !modelsData.embedding_models.some((m) => m.value === embeddingModel)
        ) {
          setEmbeddingModel("");
        }
      }
    }
  }

  return {
    languageModel,
    embeddingModel,
    setLanguageModel: !isEmbedding ? setLanguageModel : undefined,
    setEmbeddingModel: isEmbedding ? setEmbeddingModel : undefined,
    languageModels: modelsData?.language_models || [],
    embeddingModels: modelsData?.embedding_models || [],
  };
}
