import { useSyncExternalStore } from "react";

const NARROW_BREAKPOINT = 720;

/**
 * Returns true when the viewport width is at or below NARROW_BREAKPOINT.
 * Edit that constant to change when the collapsed sidebar layout kicks in.
 *
 * Uses useSyncExternalStore so the value is correct on the first client
 * render — no 1-2 second flash where the wide layout briefly renders on a
 * narrow viewport before the useEffect hydration fix kicks in.
 */

function subscribe(cb: () => void) {
  const mq = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

function getSnapshot() {
  return window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`).matches;
}

function getServerSnapshot() {
  // During SSR we don't know the viewport — default to false (wide).
  // The client will correct immediately on first paint via getSnapshot.
  return false;
}

export function useNarrowLayout(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
