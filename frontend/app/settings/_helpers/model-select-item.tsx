/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { SelectItem } from "@/components/ui/select";
import {
  getModelLogo,
  type ModelOption,
  type ModelProvider,
} from "./model-helpers";

interface ModelSelectItemProps {
  model: ModelOption;
  provider?: ModelProvider;
}

function ModelSelectItem({ model, provider }: ModelSelectItemProps) {
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
