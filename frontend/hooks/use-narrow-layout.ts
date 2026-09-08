import { useEffect, useState } from "react";

const NARROW_BREAKPOINT = 720;

/**
 * Returns true when the viewport width is at or below NARROW_BREAKPOINT.
 * Edit that constant to change when the collapsed sidebar layout kicks in.
 * Re-evaluates on resize via matchMedia — no polling.
 */
export function useNarrowLayout(): boolean {
  const [isNarrow, setIsNarrow] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth <= NARROW_BREAKPOINT;
  });

  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
    setIsNarrow(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsNarrow(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return isNarrow;
}
