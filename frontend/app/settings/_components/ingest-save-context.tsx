"use client";

import {
  createContext,
  type ReactNode,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

/**
 * `false` means the section refused to save (validation failed) and the run
 * should stop without reporting success. Anything else counts as saved.
 */
type SaveResult = boolean | void;

interface SaveEntry {
  /** Whether this section has changes worth persisting. */
  isDirty: boolean;
  /** Whether this section is in a state that must not be saved yet. */
  blocked: boolean;
  save: () => SaveResult | Promise<SaveResult>;
}

interface IngestSaveContextValue {
  register: (key: string, entry: SaveEntry) => void;
  unregister: (key: string) => void;
  isDirty: boolean;
  isBlocked: boolean;
  isSaving: boolean;
  saveAll: () => Promise<boolean>;
}

const IngestSaveContext = createContext<IngestSaveContextValue | null>(null);

/**
 * Collects the save handlers of every ingest settings section so the tab can
 * render a single Save button, as the design calls for. Sections stay owners of
 * their own state and validation; this only sequences their saves.
 */
export function IngestSaveProvider({ children }: { children: ReactNode }) {
  // Handlers live in a ref so re-registering a fresh closure on each render
  // never triggers a render of its own; only the flags below do that.
  const entriesRef = useRef<Map<string, SaveEntry>>(new Map());
  const [flags, setFlags] = useState<
    Record<string, { isDirty: boolean; blocked: boolean }>
  >({});
  const [isSaving, setIsSaving] = useState(false);

  const register = useCallback((key: string, entry: SaveEntry) => {
    entriesRef.current.set(key, entry);
    setFlags((prev) => {
      const current = prev[key];
      if (
        current &&
        current.isDirty === entry.isDirty &&
        current.blocked === entry.blocked
      ) {
        return prev;
      }
      return {
        ...prev,
        [key]: { isDirty: entry.isDirty, blocked: entry.blocked },
      };
    });
  }, []);

  const unregister = useCallback((key: string) => {
    entriesRef.current.delete(key);
    setFlags((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const isDirty = Object.values(flags).some((flag) => flag.isDirty);
  const isBlocked = Object.entries(flags).some(
    ([key, flag]) => flag.blocked && (flags[key]?.isDirty ?? false),
  );

  const saveAll = useCallback(async () => {
    setIsSaving(true);
    try {
      // Insertion order, so sections save top-to-bottom as they appear.
      for (const entry of entriesRef.current.values()) {
        if (!entry.isDirty) continue;
        if ((await entry.save()) === false) return false;
      }
      return true;
    } finally {
      setIsSaving(false);
    }
  }, []);

  const value = useMemo<IngestSaveContextValue>(
    () => ({
      register,
      unregister,
      isDirty,
      isBlocked,
      isSaving,
      saveAll,
    }),
    [register, unregister, isDirty, isBlocked, isSaving, saveAll],
  );

  return <IngestSaveContext value={value}>{children}</IngestSaveContext>;
}

function useIngestSaveContext(): IngestSaveContextValue {
  const ctx = use(IngestSaveContext);
  if (!ctx) {
    throw new Error("useIngestSave must be used within IngestSaveProvider");
  }
  return ctx;
}

/** Hand this section's dirty state and save handler to the shared Save button. */
export function useRegisterSave(key: string, entry: SaveEntry) {
  const { register, unregister } = useIngestSaveContext();

  // The handler closes over section state, so it changes every render. Keeping
  // it behind a ref lets registration depend only on the flags.
  const saveRef = useRef(entry.save);
  useEffect(() => {
    saveRef.current = entry.save;
  });

  const { isDirty, blocked } = entry;
  useEffect(() => {
    register(key, { isDirty, blocked, save: () => saveRef.current() });
  }, [key, isDirty, blocked, register]);

  useEffect(() => () => unregister(key), [key, unregister]);
}

/** Read the combined save state — for the tab's single Save button. */
export function useIngestSave() {
  const { isDirty, isBlocked, isSaving, saveAll } = useIngestSaveContext();
  return { isDirty, isBlocked, isSaving, saveAll };
}
