/**
 * Pure async logic for the GeneralTab display-name save handler.
 * Extracted so it can be unit-tested without a React rendering environment.
 */

export interface GeneralTabSaveDeps {
  mutateAsync: (vars: { display_name: string | null }) => Promise<unknown>;
  refreshAuth: () => Promise<void>;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

/**
 * Trims `value`, calls `mutateAsync` with the sanitised payload, then
 * on success refreshes auth and fires the success notification.
 * On failure fires the error notification without throwing.
 */
export async function saveDisplayName(
  value: string,
  { mutateAsync, refreshAuth, onSuccess, onError }: GeneralTabSaveDeps,
): Promise<void> {
  const trimmed = value.trim();
  try {
    await mutateAsync({ display_name: trimmed || null });
    await refreshAuth();
    onSuccess("Display name updated");
  } catch {
    onError("Failed to update display name");
  }
}
