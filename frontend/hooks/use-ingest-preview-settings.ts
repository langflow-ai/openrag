"use client";

import { useEffect, useState } from "react";

export type IngestPreviewAutoOpen = "every" | "first-run" | "never";

export interface IngestPreviewSettings {
  /** When the review opens automatically after a Knowledge ingest starts. */
  autoOpen: IngestPreviewAutoOpen;
  /** Show the per-chunk breakdown (the chunk cards). */
  showChunkBoundaries: boolean;
  /** Show the reading/chunking/embedding/stored pipeline steps. */
  showIndexingPipeline: boolean;
  /** Show each chunk's extracted text (vs. metadata only). */
  showChunkContents: boolean;
  /** Toast when ingestion finishes while the review is open. */
  completionNotification: boolean;
}

export const DEFAULT_INGEST_PREVIEW_SETTINGS: IngestPreviewSettings = {
  autoOpen: "first-run",
  showChunkBoundaries: true,
  showIndexingPipeline: true,
  showChunkContents: true,
  completionNotification: true,
};

const SETTINGS_KEY = "openrag.ingest-preview.settings";
const AUTO_OPEN_VALUES: IngestPreviewAutoOpen[] = [
  "every",
  "first-run",
  "never",
];

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
  // Value kept as first-run for localStorage compat; means onboarding only.
  {
    value: "first-run",
    label: "Onboarding only",
    description:
      "Open the review only when you upload a document during onboarding.",
  },
  {
    value: "never",
    label: "Never",
    description: "Never open the preview.",
  },
];

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
    const settings = parsed as Partial<IngestPreviewSettings>;
    return {
      autoOpen: AUTO_OPEN_VALUES.includes(
        settings.autoOpen as IngestPreviewAutoOpen,
      )
        ? (settings.autoOpen as IngestPreviewAutoOpen)
        : DEFAULT_INGEST_PREVIEW_SETTINGS.autoOpen,
      showChunkBoundaries:
        typeof settings.showChunkBoundaries === "boolean"
          ? settings.showChunkBoundaries
          : DEFAULT_INGEST_PREVIEW_SETTINGS.showChunkBoundaries,
      showIndexingPipeline:
        typeof settings.showIndexingPipeline === "boolean"
          ? settings.showIndexingPipeline
          : DEFAULT_INGEST_PREVIEW_SETTINGS.showIndexingPipeline,
      showChunkContents:
        typeof settings.showChunkContents === "boolean"
          ? settings.showChunkContents
          : DEFAULT_INGEST_PREVIEW_SETTINGS.showChunkContents,
      completionNotification:
        typeof settings.completionNotification === "boolean"
          ? settings.completionNotification
          : DEFAULT_INGEST_PREVIEW_SETTINGS.completionNotification,
    };
  } catch {
    return DEFAULT_INGEST_PREVIEW_SETTINGS;
  }
}

function writeIngestPreviewSettings(settings: IngestPreviewSettings): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

/**
 * Whether Knowledge uploads should auto-open the review.
 * Onboarding always opens when the feature flag is on (ignores this).
 * `first-run` / "Onboarding only" → Knowledge does not auto-open.
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

  const updateSettings = (patch: Partial<IngestPreviewSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      writeIngestPreviewSettings(next);
      return next;
    });
  };

  return { settings, updateSettings };
}
