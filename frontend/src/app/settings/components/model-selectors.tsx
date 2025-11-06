import { Controller, useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import { ReactNode, useEffect } from "react";
import { ModelOption } from "@/app/api/queries/useGetModelsQuery";
import { ModelSelector } from "@/app/onboarding/components/model-selector";

interface ModelSelectorsProps {
  languageModels: ModelOption[];
  embeddingModels: ModelOption[];
  isLoadingModels: boolean;
  logo: ReactNode;
  languageModelName?: string;
  embeddingModelName?: string;
}

export function ModelSelectors({
  languageModels,
  embeddingModels,
  isLoadingModels,
  logo,
  languageModelName = "llmModel",
  embeddingModelName = "embeddingModel",
}: ModelSelectorsProps) {
  const {
    control,
    watch,
    formState: { errors },
    setValue,
  } = useFormContext<Record<string, any>>();

  const llmModel = watch(languageModelName);
  const embeddingModel = watch(embeddingModelName);

  const defaultLlmModel =
    languageModels.find((model) => model.default)?.value ||
    languageModels[0]?.value;
  const defaultEmbeddingModel =
    embeddingModels.find((model) => model.default)?.value ||
    embeddingModels[0]?.value;

  useEffect(() => {
    if (defaultLlmModel && !llmModel) {
      setValue(languageModelName, defaultLlmModel, { shouldValidate: true });
    }
    if (defaultEmbeddingModel && !embeddingModel) {
      setValue(embeddingModelName, defaultEmbeddingModel, {
        shouldValidate: true,
      });
    }
  }, [
    defaultLlmModel,
    defaultEmbeddingModel,
    llmModel,
    embeddingModel,
    setValue,
    languageModelName,
    embeddingModelName,
  ]);

  return (
    <>
      <div className="space-y-2">
        <LabelWrapper
          label="Embedding model"
          helperText="Model used for knowledge ingest and retrieval"
          id="embedding-model"
          required={true}
        >
          <Controller
            control={control}
            name={embeddingModelName}
            rules={{ required: "Embedding model is required" }}
            render={({ field }) => (
              <ModelSelector
                options={embeddingModels}
                icon={logo}
                noOptionsPlaceholder={
                  isLoadingModels
                    ? "Loading models..."
                    : "No embedding models detected"
                }
                placeholder="Select an embedding model"
                value={field.value}
                onValueChange={field.onChange}
              />
            )}
          />
        </LabelWrapper>
        {embeddingModels.length > 0 && errors[embeddingModelName] && (
          <p className="text-sm text-destructive">
            {errors[embeddingModelName]?.message as string}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <LabelWrapper
          label="Language model"
          helperText="Model used for chat"
          id="language-model"
          required={true}
        >
          <Controller
            control={control}
            name={languageModelName}
            rules={{ required: "Language model is required" }}
            render={({ field }) => (
              <ModelSelector
                options={languageModels}
                icon={logo}
                noOptionsPlaceholder={
                  isLoadingModels
                    ? "Loading models..."
                    : "No language models detected"
                }
                placeholder="Select a language model"
                value={field.value}
                onValueChange={field.onChange}
              />
            )}
          />
        </LabelWrapper>
        {languageModels.length > 0 && errors[languageModelName] && (
          <p className="text-sm text-destructive">
            {errors[languageModelName]?.message as string}
          </p>
        )}
      </div>
    </>
  );
}
