"use client";

import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";

interface SidebarOverlayContextType {
  isVisible: boolean;
  show: () => void;
  hide: () => void;
}

const SidebarOverlayContext = createContext<
  SidebarOverlayContextType | undefined
>(undefined);

export function SidebarOverlayProvider({ children }: { children: ReactNode }) {
  const [isVisible, setIsVisible] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    setIsVisible(true);
  }, []);

  const hide = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null;
      setIsVisible(false);
    }, 200);
  }, []);

  const value = useMemo(
    () => ({ isVisible, show, hide }),
    [isVisible, show, hide],
  );

  return (
    <SidebarOverlayContext.Provider value={value}>
      {children}
    </SidebarOverlayContext.Provider>
  );
}

export function useSidebarOverlay(): SidebarOverlayContextType {
  const ctx = use(SidebarOverlayContext);
  if (!ctx) {
    // Outside provider (e.g. auth pages) — return a no-op.
    return { isVisible: false, show: () => {}, hide: () => {} };
  }
  return ctx;
}
