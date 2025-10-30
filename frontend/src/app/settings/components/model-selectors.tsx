import { Controller, useFormContext } from "react-hook-form";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ReactNode, useEffect } from "react";
import { ModelOption } from "@/app/api/queries/useGetModelsQuery";

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

  const defaultLlmModel = languageModels.find((model) => model.default)?.value;
  const defaultEmbeddingModel = embeddingModels.find(
    (model) => model.default
  )?.value;

  useEffect(() => {
    if (isLoadingModels) {
      setValue(languageModelName, "");
      setValue(embeddingModelName, "");
    }
  }, [isLoadingModels, setValue]);

  useEffect(() => {
    if (defaultLlmModel && !llmModel) {
    setValue(languageModelName, defaultLlmModel, { shouldValidate: true });
    }
    if (defaultEmbeddingModel && !embeddingModel) {
      setValue(embeddingModelName, defaultEmbeddingModel, { shouldValidate: true });
    }
  }, [defaultLlmModel, defaultEmbeddingModel, setValue]);

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
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={isLoadingModels || !embeddingModels.length}
              >
                <SelectTrigger id="embedding-model">
                  <div className="flex items-center gap-2">
                    {logo}
                    <SelectValue
                      placeholder={
                        isLoadingModels
                          ? "Loading models..."
                          : embeddingModels.length
                          ? "Select an embedding model"
                          : "No embedding models found"
                      }
                    />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {embeddingModels.map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </LabelWrapper>
        {errors[embeddingModelName] && (
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
              <Select
                value={field.value}
                onValueChange={field.onChange}
                disabled={isLoadingModels || !languageModels.length}
              >
                <SelectTrigger id="language-model">
                  <div className="flex items-center gap-2">
                    {logo}
                    <SelectValue
                      placeholder={
                        isLoadingModels
                          ? "Loading models..."
                          : languageModels.length
                          ? "Select a language model"
                          : "No language models found"
                      }
                    />
                  </div>
                </SelectTrigger>
                <SelectContent>
                  {languageModels.map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </LabelWrapper>
        {errors[languageModelName] && (
          <p className="text-sm text-destructive">
            {errors[languageModelName]?.message as string}
          </p>
        )}
      </div>
    </>
  );
}

