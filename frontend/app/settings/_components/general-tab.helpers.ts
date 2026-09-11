/**
 * Pure async logic for the GeneralTab display-name save handler.
 * Extracted so it can be unit-tested without a React rendering environment.
 */

export interface GeneralTabSaveDeps {
  mutateAsync: (vars: { display_name: string | null }) => Promise<unknown>;
  refreshAuth: () => Promise<void>;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
  /**
   * Called with the trimmed canonical value immediately after a successful
   * mutation, before `refreshAuth` executes.  Use to sync local input state
   * and clear any "touched" flags so the post-refresh render picks up the
   * server-canonical value.
   */
  onSaved?: (canonical: string | null) => void;
}

/**
 * Trims `value`, calls `mutateAsync` with the sanitised payload, then
 * on success syncs state, refreshes auth, and fires the success notification.
 * On failure fires the error notification without throwing.
 */
export async function saveDisplayName(
  value: string,
  { mutateAsync, refreshAuth, onSuccess, onError, onSaved }: GeneralTabSaveDeps,
): Promise<void> {
  const trimmed = value.trim();
  const canonical = trimmed || null;
  try {
    await mutateAsync({ display_name: canonical });
    onSaved?.(canonical);
    await refreshAuth();
    onSuccess("Display name updated");
  } catch {
    onError("Failed to update display name");
  }
}
