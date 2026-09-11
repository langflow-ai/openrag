/**
 * Pure async logic for the OnboardingPersonalization save handler.
 * Extracted so it can be unit-tested without a React rendering environment.
 */

export interface SaveDisplayNameDeps {
  mutateAsync: (vars: { display_name: string | null }) => Promise<unknown>;
  refreshAuth: () => Promise<void>;
  onComplete: () => void;
  onError: (message: string) => void;
}

/**
 * Trims `value`, calls `mutateAsync` with the sanitised payload, then
 * on success refreshes auth and advances the wizard.  On failure calls
 * `onError` with a user-facing message without calling `onComplete`.
 */
export async function saveDisplayName(
  value: string,
  { mutateAsync, refreshAuth, onComplete, onError }: SaveDisplayNameDeps,
): Promise<void> {
  const trimmed = value.trim();
  try {
    await mutateAsync({ display_name: trimmed || null });
    await refreshAuth();
    onComplete();
  } catch {
    onError("Failed to save display name. Please try again.");
  }
}
