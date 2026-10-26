import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { CatalogSelectOption } from "@/components/models/catalog-models";
import { requiresExplicitModelSelection } from "@/components/models/model-helpers";

export interface OnboardingModelSelection {
  /** The model Submit uses: the user's pick, or the list's default. */
  model: string;
  /** Records the user's own choice, which then wins over the default. */
  pickModel: (model: string) => void;
}

/**
 * The model an onboarding step submits, given the picker's current options.
 *
 * Only the user's own pick is state; otherwise the model follows the list.
 * Azure's catalogue lists model families, not this customer's deployments,
 * so it requires an explicit choice. Other providers default to the
 * highest-ranked model, which tracks the list as discovery replaces the
 * configured fallback — a model the cluster does not serve never stays
 * selected — while a pick is kept even when the cluster does not list it.
 */
export function useOnboardingModelSelection({
  provider,
  models,
  inFlight,
  onModelChange,
}: {
  provider: string;
  models: CatalogSelectOption[];
  /** Discovery has no answer yet for the credentials as typed. */
  inFlight: boolean;
  /** Called on every change of the effective model, never on mount with "". */
  onModelChange: (model: string) => void;
}): OnboardingModelSelection {
  const [pickedModel, setPickedModel] = useState<string | null>(null);
  const defaultModel = requiresExplicitModelSelection(provider)
    ? ""
    : (models[0]?.value ?? "");
  // While the cluster is asked again the list briefly falls back to the
  // configured rows: keep the last settled default rather than flick to one of
  // those and back. With nothing to keep, follow the list: saved credentials
  // start discovery as soon as the catalogue loads, and a slow cluster must
  // not leave Submit without a model meanwhile.
  const [settledDefault, setSettledDefault] = useState("");
  if (!inFlight && settledDefault !== defaultModel) {
    setSettledDefault(defaultModel);
  }
  const model =
    pickedModel ?? (inFlight && settledDefault ? settledDefault : defaultModel);

  const notifyModelChange = useEffectEvent(onModelChange);
  // Mirror every change, including an automatic choice the list no longer
  // offers; mount stays a no-op so an empty model isn't written up front.
  const syncedModelRef = useRef("");
  useEffect(() => {
    if (model === syncedModelRef.current) return;
    syncedModelRef.current = model;
    notifyModelChange(model);
  }, [model]);

  return { model, pickModel: setPickedModel };
}
