import { useEffect, useState } from "react";

/**
 * Returns `value` after it has stopped changing for `delayMs`.
 *
 * A debounce restarts on every change, so it fires on the first pause longer
 * than `delayMs` rather than waiting for a whole word. A `delayMs` of 0 applies
 * the value on the next tick, which callers use to skip the wait at word
 * boundaries.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
