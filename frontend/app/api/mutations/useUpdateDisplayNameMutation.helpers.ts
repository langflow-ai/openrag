/**
 * Pure fetch logic for the display-name PATCH mutation.
 * Extracted so it can be unit-tested without React / React Query.
 */

export interface DisplayNameResult {
  display_name: string | null;
}

/**
 * Calls PATCH /api/users/me/display-name.
 * Throws with the API's `detail` message (or a fallback) on non-2xx.
 */
export async function patchDisplayName(
  display_name: string | null,
  fetchFn: typeof fetch = fetch,
): Promise<DisplayNameResult> {
  const response = await fetchFn("/api/users/me/display-name", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(
      (err as { detail?: string }).detail ?? "Failed to save display name",
    );
  }
  return response.json() as Promise<DisplayNameResult>;
}
