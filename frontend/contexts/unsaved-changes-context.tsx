"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getInterceptedNavigationHref } from "@/lib/navigation-events";

type NavigationAction = () => void | Promise<void>;

type PendingNavigation =
  | { type: "href"; href: string }
  | { type: "action"; action: NavigationAction }
  | { type: "history"; delta: number };

interface UnsavedChangesContextValue {
  register: (key: string, isDirty: boolean) => void;
  unregister: (key: string) => void;
  hasUnsavedChanges: boolean;
  guardNavigation: (href: string, action?: NavigationAction) => boolean;
  showDialog: boolean;
  confirmLeave: () => void;
  cancelLeave: () => void;
}

const UnsavedChangesContext = createContext<UnsavedChangesContextValue | null>(
  null,
);

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [dirtyMap, setDirtyMap] = useState<Record<string, boolean>>({});
  const [pendingNavigation, setPendingNavigation] =
    useState<PendingNavigation | null>(null);

  const register = useCallback((key: string, isDirty: boolean) => {
    setDirtyMap((prev) => {
      if (prev[key] === isDirty) return prev;
      return { ...prev, [key]: isDirty };
    });
  }, []);

  const unregister = useCallback((key: string) => {
    setDirtyMap((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const hasUnsavedChanges = Object.values(dirtyMap).some(Boolean);
  const hasUnsavedRef = useRef(hasUnsavedChanges);

  useEffect(() => {
    hasUnsavedRef.current = hasUnsavedChanges;
  }, [hasUnsavedChanges]);

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!hasUnsavedRef.current) return;
      const anchor = (e.target as HTMLElement).closest("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href) return;
      const interceptedHref = getInterceptedNavigationHref({
        button: e.button,
        href,
        currentHref: window.location.href,
        target: anchor.target,
        download: anchor.hasAttribute("download"),
        metaKey: e.metaKey,
        ctrlKey: e.ctrlKey,
        shiftKey: e.shiftKey,
        altKey: e.altKey,
      });
      if (!interceptedHref) return;

      e.preventDefault();
      e.stopPropagation();
      setPendingNavigation({ type: "href", href: interceptedHref });
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, []);

  const hasHistorySentinelRef = useRef(false);
  const restoringHistoryRef = useRef(false);
  const confirmedActionRef = useRef<NavigationAction | null>(null);

  useEffect(() => {
    if (hasUnsavedChanges && !hasHistorySentinelRef.current) {
      window.history.pushState(window.history.state, "", window.location.href);
      hasHistorySentinelRef.current = true;
      return;
    }

    if (!hasUnsavedChanges && hasHistorySentinelRef.current) {
      restoringHistoryRef.current = true;
      hasHistorySentinelRef.current = false;
      window.history.back();
    }
  }, [hasUnsavedChanges]);

  useEffect(() => {
    const handler = (e: PopStateEvent) => {
      if (confirmedActionRef.current) {
        e.stopImmediatePropagation();
        const action = confirmedActionRef.current;
        confirmedActionRef.current = null;
        void action();
        return;
      }

      if (restoringHistoryRef.current) {
        e.stopImmediatePropagation();
        restoringHistoryRef.current = false;
        return;
      }

      if (!hasUnsavedRef.current) return;

      e.stopImmediatePropagation();
      setPendingNavigation({ type: "history", delta: -2 });
      restoringHistoryRef.current = true;
      window.history.forward();
    };

    window.addEventListener("popstate", handler, true);
    return () => window.removeEventListener("popstate", handler, true);
  }, []);

  const guardNavigation = useCallback(
    (href: string, action?: NavigationAction): boolean => {
      if (!hasUnsavedChanges) return true;
      setPendingNavigation(
        action ? { type: "action", action } : { type: "href", href },
      );
      return false;
    },
    [hasUnsavedChanges],
  );

  const confirmLeave = useCallback(() => {
    if (!pendingNavigation) return;

    setPendingNavigation(null);
    hasUnsavedRef.current = false;

    if (pendingNavigation.type === "history") {
      hasHistorySentinelRef.current = false;
      window.history.go(pendingNavigation.delta);
      return;
    }

    const action =
      pendingNavigation.type === "action"
        ? pendingNavigation.action
        : () => router.push(pendingNavigation.href);

    if (hasHistorySentinelRef.current) {
      hasHistorySentinelRef.current = false;
      confirmedActionRef.current = action;
      window.history.back();
      return;
    }

    void action();
  }, [pendingNavigation, router]);

  const cancelLeave = useCallback(() => {
    setPendingNavigation(null);
  }, []);

  const value = useMemo<UnsavedChangesContextValue>(
    () => ({
      register,
      unregister,
      hasUnsavedChanges,
      guardNavigation,
      showDialog: pendingNavigation !== null,
      confirmLeave,
      cancelLeave,
    }),
    [
      register,
      unregister,
      hasUnsavedChanges,
      guardNavigation,
      pendingNavigation,
      confirmLeave,
      cancelLeave,
    ],
  );

  return (
    <UnsavedChangesContext.Provider value={value}>
      {children}
    </UnsavedChangesContext.Provider>
  );
}

export function useRegisterDirty(key: string, isDirty: boolean) {
  const ctx = useContext(UnsavedChangesContext);
  if (!ctx) {
    throw new Error(
      "useRegisterDirty must be used within UnsavedChangesProvider",
    );
  }

  const { register, unregister } = ctx;

  useEffect(() => {
    register(key, isDirty);
  }, [key, isDirty, register]);

  useEffect(() => {
    return () => unregister(key);
  }, [key, unregister]);
}

export function useUnsavedChangesGuard() {
  const ctx = useContext(UnsavedChangesContext);
  if (!ctx) {
    throw new Error(
      "useUnsavedChangesGuard must be used within UnsavedChangesProvider",
    );
  }
  return {
    guardNavigation: ctx.guardNavigation,
    showDialog: ctx.showDialog,
    confirmLeave: ctx.confirmLeave,
    cancelLeave: ctx.cancelLeave,
  };
}
