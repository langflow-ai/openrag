"use client";

import { useEffect, useState } from "react";

export type IngestPreviewAutoOpen = "every" | "never";

export interface IngestPreviewSettings {
  /** When the review opens automatically after a Knowledge ingest starts. */
  autoOpen: IngestPreviewAutoOpen;
  /**
   * Always-on preview chrome. Kept on the settings object for IngestReview,
   * but no longer user-configurable — persisted false values are ignored.
   */
  showChunkBoundaries: boolean;
  showIndexingPipeline: boolean;
  showChunkContents: boolean;
  completionNotification: boolean;
}

export const DEFAULT_INGEST_PREVIEW_SETTINGS: IngestPreviewSettings = {
  autoOpen: "never",
  showChunkBoundaries: true,
  showIndexingPipeline: true,
  showChunkContents: true,
  completionNotification: true,
};

const SETTINGS_KEY = "openrag.ingest-preview.settings";

/** Former Settings toggles. Still present in some localStorage blobs. */
const LEGACY_PREVIEW_FLAG_KEYS = [
  "showChunkBoundaries",
  "showIndexingPipeline",
  "showChunkContents",
  "completionNotification",
] as const;

export const INGEST_PREVIEW_AUTO_OPEN_OPTIONS: ReadonlyArray<{
  value: IngestPreviewAutoOpen;
  label: string;
  description: string;
}> = [
  {
    value: "every",
    label: "Every upload",
    description: "Open the review automatically when a document is ingested.",
  },
  {
    value: "never",
    label: "Never",
    description: "Never open the preview.",
  },
];

/** Map legacy localStorage values to the current two-option set. */
function normalizeAutoOpen(value: unknown): IngestPreviewAutoOpen | null {
  if (value === "every" || value === "never") return value;
  // Former "Onboarding only" — same Knowledge behavior as Never.
  if (value === "first-run") return "never";
  return null;
}

function writeIngestPreviewSettings(settings: IngestPreviewSettings): void {
  if (typeof window === "undefined") return;
  // Only autoOpen is user-configurable; drop removed toggle keys on write.
  window.localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({ autoOpen: settings.autoOpen }),
  );
}

/** Read persisted settings, falling back to defaults for any missing/invalid field. */
export function readIngestPreviewSettings(): IngestPreviewSettings {
  if (typeof window === "undefined") {
    return DEFAULT_INGEST_PREVIEW_SETTINGS;
  }
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_INGEST_PREVIEW_SETTINGS;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed === null ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      return DEFAULT_INGEST_PREVIEW_SETTINGS;
    }
    const stored = parsed as Record<string, unknown>;
    const settings: IngestPreviewSettings = {
      autoOpen:
        normalizeAutoOpen(stored.autoOpen) ??
        DEFAULT_INGEST_PREVIEW_SETTINGS.autoOpen,
      // Toggles were removed from Settings; ignore any persisted false values
      // so users cannot get stuck with hidden preview chrome.
      showChunkBoundaries: DEFAULT_INGEST_PREVIEW_SETTINGS.showChunkBoundaries,
      showIndexingPipeline:
        DEFAULT_INGEST_PREVIEW_SETTINGS.showIndexingPipeline,
      showChunkContents: DEFAULT_INGEST_PREVIEW_SETTINGS.showChunkContents,
      completionNotification:
        DEFAULT_INGEST_PREVIEW_SETTINGS.completionNotification,
    };
    if (LEGACY_PREVIEW_FLAG_KEYS.some((key) => key in stored)) {
      writeIngestPreviewSettings(settings);
    }
    return settings;
  } catch {
    return DEFAULT_INGEST_PREVIEW_SETTINGS;
  }
}

/**
 * Whether Knowledge uploads should auto-open the review.
 * Onboarding always opens when the feature flag is on (ignores this).
 * `never` → Knowledge does not auto-open.
 */
export function shouldAutoOpenIngestPreview(
  settings: IngestPreviewSettings = readIngestPreviewSettings(),
): boolean {
  return settings.autoOpen === "every";
}

/** Stateful accessor for the settings form; persists on every change. */
export function useIngestPreviewSettings() {
  const [settings, setSettings] = useState<IngestPreviewSettings>(
    DEFAULT_INGEST_PREVIEW_SETTINGS,
  );

  useEffect(() => {
    setSettings(readIngestPreviewSettings());
  }, []);

  const updateSettings = (patch: Pick<IngestPreviewSettings, "autoOpen">) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      writeIngestPreviewSettings(next);
      return next;
    });
  };

  return { settings, updateSettings };
}
