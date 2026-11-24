import { getModelLogo } from "@/components/models/model-helpers";
import type { GroupedModelOption } from "@/components/models/model-selector";

/**
 * "Docling default" lets docling-serve pick the picture-description model
 * itself (its stock preset is SmolVLM-256M-Instruct, but an operator can change
 * it). It is not a model id: selecting it saves `vlm_enabled: false` and
 * `vlm_provider: "docling"`, so the backend sends docling-serve no
 * `picture_description_*` block at all. The provider marker is what keeps the
 * choice after picture descriptions are turned off; `vlm_model` cannot be
 * cleared (the API rejects an empty string), so it keeps the last real model.
 */
export const DOCLING_DEFAULT_VLM_VALUE = "__docling_default__";
export const DOCLING_DEFAULT_VLM_PROVIDER = "docling";
export const DOCLING_DEFAULT_VLM_LABEL =
  "Docling default (SmolVLM-256M-Instruct)";

export type VlmSelection = { model: string; provider: string };

type SavedVlmSettings = {
  picture_descriptions?: boolean;
  vlm_enabled?: boolean;
  vlm_model?: string;
  vlm_provider?: string;
};

export function isDoclingDefaultVlm(model: string): boolean {
  return model === DOCLING_DEFAULT_VLM_VALUE;
}

/**
 * The selection the saved settings represent. A saved model is kept while
 * picture descriptions are off, because the save path stores `vlm_enabled`
 * as false then too. "On but not enabled" also means Docling default, which
 * covers settings saved while the VLM section was hidden.
 */
export function savedVlmSelection(saved?: SavedVlmSettings): VlmSelection {
  const model = saved?.vlm_model?.trim() ?? "";
  if (
    !model ||
    saved?.vlm_provider === DOCLING_DEFAULT_VLM_PROVIDER ||
    (saved?.picture_descriptions && saved.vlm_enabled === false)
  ) {
    return {
      model: DOCLING_DEFAULT_VLM_VALUE,
      provider: DOCLING_DEFAULT_VLM_PROVIDER,
    };
  }
  return { model, provider: saved?.vlm_provider ?? "" };
}

export function doclingDefaultVlmGroup(): GroupedModelOption {
  return {
    group: "Docling",
    provider: DOCLING_DEFAULT_VLM_PROVIDER,
    icon: getModelLogo("", "local"),
    options: [
      {
        value: DOCLING_DEFAULT_VLM_VALUE,
        label: DOCLING_DEFAULT_VLM_LABEL,
        provider: DOCLING_DEFAULT_VLM_PROVIDER,
      },
    ],
  };
}
