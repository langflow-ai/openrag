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
  isPinned: boolean;
  isCollapsed: boolean;
  show: () => void;
  hide: () => void;
  hideNow: () => void;
  pin: () => void;
  unpin: () => void;
  expand: () => void;
  collapse: () => void;
}

const SidebarOverlayContext = createContext<
  SidebarOverlayContextType | undefined
>(undefined);

export function SidebarOverlayProvider({ children }: { children: ReactNode }) {
  const [isVisible, setIsVisible] = useState(false);
  const [isPinned, setIsPinned] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    setIsVisible(true);
  }, []);

  const hide = useCallback(() => {
    if (isPinned) return;
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null;
      setIsVisible(false);
    }, 200);
  }, [isPinned]);

  const pin = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    setIsPinned(true);
    setIsVisible(true);
  }, []);

  const unpin = useCallback(() => {
    setIsPinned(false);
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    hideTimerRef.current = setTimeout(() => {
      hideTimerRef.current = null;
      setIsVisible(false);
    }, 200);
  }, []);

  const hideNow = useCallback(() => {
    if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    setIsVisible(false);
  }, []);

  const collapse = useCallback(() => setIsCollapsed(true), []);
  const expand = useCallback(() => setIsCollapsed(false), []);

  const value = useMemo(
    () => ({
      isVisible,
      isPinned,
      isCollapsed,
      show,
      hide,
      hideNow,
      pin,
      unpin,
      expand,
      collapse,
    }),
    [
      isVisible,
      isPinned,
      isCollapsed,
      show,
      hide,
      hideNow,
      pin,
      unpin,
      expand,
      collapse,
    ],
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
    return {
      isVisible: false,
      isPinned: false,
      isCollapsed: false,
      show: () => {},
      hide: () => {},
      hideNow: () => {},
      pin: () => {},
      unpin: () => {},
      expand: () => {},
      collapse: () => {},
    };
  }
  return ctx;
}
