"use client";

import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { TOTAL_ONBOARDING_STEPS } from "@/lib/constants";

export function useOnboardingState() {
  const { data: settings } = useGetSettingsQuery();
  const currentStep = settings?.onboarding?.current_step;
  const isValidStep =
    typeof currentStep === "number" && Number.isFinite(currentStep);
  const isOnboardingComplete =
    isValidStep && currentStep >= TOTAL_ONBOARDING_STEPS;
  const isOnboardingActive =
    isValidStep && currentStep < TOTAL_ONBOARDING_STEPS;

  return { isOnboardingComplete, isOnboardingActive, currentStep };
}
