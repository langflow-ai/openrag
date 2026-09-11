/** User utility helpers shared across features. */

interface UserLike {
  display_name?: string | null;
  name?: string | null;
}

/**
 * Resolves the best available display name for a user.
 * Prefers `display_name`, falls back to the OAuth `name` (excluding the
 * "Anonymous User" sentinel), returns null when no name is available.
 */
export function resolveDisplayName(
  user: UserLike | null | undefined,
): string | null {
  if (!user) return null;
  if (user.display_name) return user.display_name;
  if (user.name && user.name !== "Anonymous User") return user.name;
  return null;
}
