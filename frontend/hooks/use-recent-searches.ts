import { useCallback, useEffect, useState } from "react";
import { useOptionalAuth } from "@/contexts/auth-context";
import {
  pushRecentSearch,
  readRecentSearches,
  recentSearchesKey,
  writeRecentSearches,
} from "@/lib/recent-searches";

/** The signed-in user's recently submitted searches, newest first. */
export function useRecentSearches() {
  const userId = useOptionalAuth()?.user?.user_id;
  const key = recentSearchesKey(userId);
  const [recent, setRecent] = useState<string[]>([]);

  // Read after mount: localStorage does not exist during server rendering.
  useEffect(() => {
    setRecent(readRecentSearches(key));
  }, [key]);

  const remember = useCallback(
    (query: string) => {
      // Re-read so a second tab's searches are not overwritten.
      const next = pushRecentSearch(readRecentSearches(key), query);
      writeRecentSearches(key, next);
      setRecent(next);
    },
    [key],
  );

  return { recent, remember };
}
