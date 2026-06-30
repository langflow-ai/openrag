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
