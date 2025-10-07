import { ModelOption } from "@/app/api/queries/useGetModelsQuery";
import {
  getFallbackModels,
  ModelProvider,
} from "@/app/settings/helpers/model-helpers";
import { ModelSelectItems } from "@/app/settings/helpers/model-select-item";
import { LabelWrapper } from "@/components/label-wrapper";
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@radix-ui/react-select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@radix-ui/react-tooltip";

interface EmbeddingModelInputProps {
  disabled?: boolean;
  value: string;
  onChange: (value: string) => void;
  modelsData?: {
    embedding_models: ModelOption[];
  };
  currentProvider?: ModelProvider;
}

export const EmbeddingModelInput = ({
  disabled,
  value,
  onChange,
  modelsData,
  currentProvider = "openai",
}: EmbeddingModelInputProps) => {
  return (
    <LabelWrapper
      helperText="Model used for knowledge ingest and retrieval"
      id="embedding-model-select"
      label="Embedding model"
    >
      <Select disabled={disabled} value={value} onValueChange={onChange}>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <SelectTrigger disabled id="embedding-model-select">
              <SelectValue placeholder="Select an embedding model" />
            </SelectTrigger>
          </TooltipTrigger>
          <TooltipContent>Locked to keep embeddings consistent</TooltipContent>
        </Tooltip>
        <SelectContent>
          <ModelSelectItems
            models={modelsData?.embedding_models}
            fallbackModels={getFallbackModels(currentProvider).embedding}
            provider={currentProvider}
          />
        </SelectContent>
      </Select>
    </LabelWrapper>
  );
};
