import { SelectItem } from "@/components/ui/select";
import {
  getModelLogo,
  type ModelProvider,
  type ModelOption,
} from "./model-helpers";

interface ModelSelectItemProps {
  model: ModelOption;
  provider?: ModelProvider;
}

export function ModelSelectItem({ model, provider }: ModelSelectItemProps) {
  return (
    <SelectItem value={model.value}>
      <div className="flex items-center gap-2">
        {getModelLogo(model.value, provider)}
        <span>{model.label}</span>
      </div>
    </SelectItem>
  );
}

interface ModelSelectItemsProps {
  models?: ModelOption[];
  fallbackModels: ModelOption[];
  provider: ModelProvider;
}

export function ModelSelectItems({
  models,
  fallbackModels,
  provider,
}: ModelSelectItemsProps) {
  const modelsToRender = models || fallbackModels;

  return (
    <>
      {modelsToRender.map((model) => (
        <ModelSelectItem key={model.value} model={model} provider={provider} />
      ))}
    </>
  );
}
