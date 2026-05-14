"use client";

import { useGetSettingsQuery } from "@/app/api/queries/useGetSettingsQuery";
import { TOTAL_ONBOARDING_STEPS } from "@/lib/constants";

export function useOnboardingState() {
  const { data: settings } = useGetSettingsQuery();
  const currentStep = settings?.onboarding?.current_step;
  const isOnboardingComplete =
    currentStep !== undefined && currentStep >= TOTAL_ONBOARDING_STEPS;
  const isOnboardingActive =
    currentStep !== undefined && currentStep < TOTAL_ONBOARDING_STEPS;

  return { isOnboardingComplete, isOnboardingActive, currentStep };
}
