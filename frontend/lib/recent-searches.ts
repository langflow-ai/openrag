export const RECENT_SEARCHES_MAX = 10;

const STORAGE_PREFIX = "openrag:recent-searches:";

/** One list per user, so a shared browser never shows someone else's queries. */
export function recentSearchesKey(userId?: string | null): string {
  return `${STORAGE_PREFIX}${userId ?? "anonymous"}`;
}

const normalize = (value: string) => value.trim().replace(/\s+/g, " ");

/** Put `query` first, dropping any earlier case-insensitive duplicate (LRU order). */
export function pushRecentSearch(
  list: string[],
  query: string,
  max = RECENT_SEARCHES_MAX,
): string[] {
  const text = normalize(query);
  if (!text) return list;
  const lower = text.toLowerCase();
  return [
    text,
    ...list.filter((item) => normalize(item).toLowerCase() !== lower),
  ].slice(0, max);
}

export function readRecentSearches(key: string): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string")
      .slice(0, RECENT_SEARCHES_MAX);
  } catch {
    return [];
  }
}

export function writeRecentSearches(key: string, list: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(list));
  } catch {
    // Storage can be unavailable (private mode, quota); history is best-effort.
  }
}
