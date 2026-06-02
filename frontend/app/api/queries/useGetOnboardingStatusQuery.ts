import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface OnboardingStatus {
  onboarded: boolean;
  /** Step indicator from OnboardingState — historically an integer
   * index, may become a named step in future. Treat as opaque. */
  current_step: number | string | null;
}

/**
 * Public query — hits GET /api/onboarding-status. The endpoint is
 * unauthenticated so this works pre-login and is used by the auth
 * context to decide between rendering the onboarding wizard and the
 * login flow.
 */
export const useGetOnboardingStatusQuery = (
  options?: Omit<UseQueryOptions<OnboardingStatus>, "queryKey" | "queryFn">,
) => {
  async function fetchStatus(): Promise<OnboardingStatus> {
    const response = await fetch("/api/onboarding-status");
    if (response.ok) return await response.json();
    // Conservative fallback: assume NOT onboarded if the endpoint is
    // unreachable. Avoids accidentally hiding the wizard on a brand-new
    // install whose backend is still booting.
    return { onboarded: false, current_step: null };
  }

  return useQuery({
    queryKey: ["onboarding-status"],
    queryFn: fetchStatus,
    staleTime: Infinity, // doesn't change during a session
    ...options,
  });
};
