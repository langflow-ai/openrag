/** User utility helpers shared across features. */

interface UserLike {
  name?: string | null;
}

/**
 * Resolves the best available display name for a user from their OAuth name.
 * Excludes the "Anonymous User" sentinel, returns null when no name is available.
 */
export function resolveDisplayName(
  user: UserLike | null | undefined,
): string | null {
  if (!user) return null;
  if (user.name && user.name !== "Anonymous User") return user.name;
  return null;
}
