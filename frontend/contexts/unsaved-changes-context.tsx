"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

interface UnsavedChangesContextValue {
  register: (key: string, isDirty: boolean) => void;
  unregister: (key: string) => void;
  hasUnsavedChanges: boolean;
  guardNavigation: (href: string) => boolean;
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
  const [pendingHref, setPendingHref] = useState<string | null>(null);

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
  hasUnsavedRef.current = hasUnsavedChanges;

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  const setPendingRef = useRef(setPendingHref);
  setPendingRef.current = setPendingHref;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!hasUnsavedRef.current) return;
      const anchor = (e.target as HTMLElement).closest("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("/settings")) return;
      if (anchor.target === "_blank") return;

      e.preventDefault();
      e.stopPropagation();
      setPendingRef.current(href);
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, []);

  const guardNavigation = useCallback(
    (href: string): boolean => {
      if (!hasUnsavedChanges) return true;
      setPendingHref(href);
      return false;
    },
    [hasUnsavedChanges],
  );

  const confirmLeave = useCallback(() => {
    if (pendingHref) {
      router.push(pendingHref);
    }
    setPendingHref(null);
  }, [pendingHref, router]);

  const cancelLeave = useCallback(() => {
    setPendingHref(null);
  }, []);

  return (
    <UnsavedChangesContext.Provider
      value={{
        register,
        unregister,
        hasUnsavedChanges,
        guardNavigation,
        showDialog: pendingHref !== null,
        confirmLeave,
        cancelLeave,
      }}
    >
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

  const registerRef = useRef(ctx.register);
  registerRef.current = ctx.register;
  const unregisterRef = useRef(ctx.unregister);
  unregisterRef.current = ctx.unregister;

  useEffect(() => {
    registerRef.current(key, isDirty);
  }, [key, isDirty]);

  useEffect(() => {
    return () => unregisterRef.current(key);
  }, [key]);
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
