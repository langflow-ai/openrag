/** Ingest preview helpers (run-mode UI gate; backend also requires the env flag). */

import { IBM_THEME_DEV } from "@/lib/brand";

/**
 * Eligible run modes for showing ingest-preview UI.
 * SaaS omitted until product approval — add "saas" here to restore.
 * The backend still requires `OPENRAG_INGEST_PREVIEW_ENABLED=true` before
 * `preview_mode` is honored — uploads then report `preview_mode` in the 202 body.
 */
const INGEST_PREVIEW_RUN_MODES = new Set(["oss"]);

/**
 * Client-side gate for showing ingest-preview UI.
 * Currently OSS only; SaaS deferred pending product approval.
 *
 * Local IBM theme (`NEXT_PUBLIC_IBM_THEME_DEV`): the header OSS/IBM switch does
 * not change backend `runMode`, so pass `isCloudBrand` to hide preview in the
 * IBM/SaaS brand view the same way real `OPENRAG_RUN_MODE=saas` would.
 */
export function isIngestPreviewEnabled(
  runMode: string | null | undefined,
  options?: { isCloudBrand?: boolean },
): boolean {
  if (runMode == null || !INGEST_PREVIEW_RUN_MODES.has(runMode)) {
    return false;
  }
  if (IBM_THEME_DEV && options?.isCloudBrand) {
    return false;
  }
  return true;
}

export type ChunkPageNumbering = "zero-based" | "one-based";

/** One pass over chunks: distinct page count + Docling page numbering. */
export function summarizeChunkPages(
  chunks: ReadonlyArray<{ page?: number | null }>,
): { pageCount: number; numbering: ChunkPageNumbering } {
  const pages = new Set<number>();
  let minPage: number | undefined;
  for (const chunk of chunks) {
    const page = chunk.page;
    if (typeof page !== "number") continue;
    pages.add(page);
    if (minPage === undefined || page < minPage) {
      minPage = page;
    }
  }
  return {
    pageCount: pages.size,
    numbering: minPage === 0 ? "zero-based" : "one-based",
  };
}

function pageHasEmbeddedImage(page: unknown): boolean {
  const image = (page as { image?: unknown } | null)?.image;
  if (!image) return false;
  if (typeof image === "string") return image.length > 0;
  const { uri, data } = image as { uri?: unknown; data?: unknown };
  return Boolean(uri) || Boolean(data);
}

/**
 * Whether the Docling JSON embeds full-page renderings. Only PDFs and image
 * inputs produce these; office formats parse to structured items without page
 * rasters, so `docling-img` would render blank for them.
 */
export function doclingHasPageImages(
  document: Record<string, unknown>,
): boolean {
  const pages = (document as { pages?: unknown }).pages;
  if (!pages) return false;
  if (Array.isArray(pages)) {
    for (const page of pages) {
      if (pageHasEmbeddedImage(page)) return true;
    }
    return false;
  }
  for (const key of Object.keys(pages as object)) {
    if (pageHasEmbeddedImage((pages as Record<string, unknown>)[key])) {
      return true;
    }
  }
  return false;
}

/** Shared state shape for ingest-review dialog open from Knowledge / onboarding. */
export type PreviewDialogState = {
  open: boolean;
  taskIds: string[];
  filename: string;
  files: File[];
};

export const EMPTY_PREVIEW: PreviewDialogState = {
  open: false,
  taskIds: [],
  filename: "",
  files: [],
};

type DoclingProv = { page_no?: number };

type MatchableDoclingItem = {
  self_ref?: string;
  text?: string;
  orig?: string;
  prov?: DoclingProv[];
  data?: { grid?: Array<Array<{ text?: string }>> };
};

function normalizeMatchText(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

function itemPlainText(item: MatchableDoclingItem): string {
  if (typeof item.text === "string" && item.text.trim()) {
    return item.text;
  }
  // PDF/Docling items sometimes expose content on `orig` instead of `text`.
  if (typeof item.orig === "string" && item.orig.trim()) {
    return item.orig;
  }
  const grid = item.data?.grid;
  if (!Array.isArray(grid)) return "";
  return grid.flatMap((row) => row.map((cell) => cell?.text ?? "")).join(" ");
}

function itemPages(item: MatchableDoclingItem): number[] {
  if (!Array.isArray(item.prov)) return [];
  const pages: number[] = [];
  for (const prov of item.prov) {
    if (typeof prov.page_no === "number") pages.push(prov.page_no);
  }
  return pages;
}

function scoreTextOverlap(chunkText: string, itemText: string): number {
  const chunk = normalizeMatchText(chunkText);
  const item = normalizeMatchText(itemText);
  if (!chunk || !item) return 0;
  if (chunk.includes(item) || item.includes(chunk)) {
    return (
      Math.min(chunk.length, item.length) / Math.max(chunk.length, item.length)
    );
  }
  const chunkTokens = new Set(chunk.split(" ").filter((t) => t.length > 2));
  if (chunkTokens.size === 0) return 0;
  let hits = 0;
  for (const token of item.split(" ")) {
    if (chunkTokens.has(token)) hits += 1;
  }
  return hits / chunkTokens.size;
}

const MIN_MATCH_SCORE = 0.2;

export type ChunkDoclingMatch = {
  /** Matched layout item refs (for text-preview emphasis / PDF itemPart). */
  itemRefs: string[];
  /** True when we fell back to the whole page. */
  pageFallback: boolean;
  /** Docling 1-based page for scroll/overlay (from match prov or chunk page). */
  page?: number;
};

/**
 * Map an indexed chunk to Docling layout item refs by text overlap.
 * Chunk page is a hint only — indexed page metadata is often wrong/stale, so
 * when nothing matches on that page we search the whole document.
 */
export function matchChunkToDoclingItems(
  document: Record<string, unknown> | null | undefined,
  chunk: { page?: number | null; text: string },
  numbering: ChunkPageNumbering = "one-based",
): ChunkDoclingMatch | null {
  if (typeof chunk.page !== "number" && !chunk.text.trim()) {
    return null;
  }

  const doclingPage =
    typeof chunk.page === "number"
      ? numbering === "zero-based"
        ? chunk.page + 1
        : chunk.page
      : null;

  const pageFallback =
    doclingPage != null
      ? {
          itemRefs: [] as string[],
          pageFallback: true,
          page: doclingPage,
        }
      : null;

  if (!document) return pageFallback;

  type Candidate = { ref: string; score: number; page?: number };
  const collections: Array<{ key: string; items: unknown }> = [
    { key: "texts", items: document.texts },
    { key: "tables", items: document.tables },
    { key: "pictures", items: document.pictures },
  ];

  const collectCandidates = (restrictPage: number | null): Candidate[] => {
    const candidates: Candidate[] = [];
    for (const { key, items } of collections) {
      if (!Array.isArray(items)) continue;
      for (let i = 0; i < items.length; i += 1) {
        const item = items[i] as MatchableDoclingItem;
        const pages = itemPages(item);
        if (
          restrictPage != null &&
          pages.length > 0 &&
          !pages.includes(restrictPage)
        ) {
          continue;
        }
        const plain = itemPlainText(item);
        const score = scoreTextOverlap(chunk.text, plain);
        if (score < MIN_MATCH_SCORE) continue;
        const ref =
          typeof item.self_ref === "string" && item.self_ref.startsWith("#/")
            ? item.self_ref
            : `#/${key}/${i}`;
        candidates.push({
          ref,
          score,
          page: pages[0],
        });
      }
    }
    return candidates;
  };

  // Prefer same-page matches, then search all pages by text (page metadata
  // on indexed chunks is frequently missing or stuck on page 1).
  let candidates = collectCandidates(doclingPage);
  if (candidates.length === 0) {
    candidates = collectCandidates(null);
  }

  if (candidates.length === 0) return pageFallback;

  candidates.sort((a, b) => b.score - a.score);
  const top = candidates[0]?.score ?? 0;
  const threshold = Math.max(MIN_MATCH_SCORE, top * 0.6);
  const itemRefs: string[] = [];
  for (const candidate of candidates) {
    if (candidate.score < threshold) break;
    itemRefs.push(candidate.ref);
    if (itemRefs.length >= 8) break;
  }
  return {
    itemRefs,
    pageFallback: false,
    page: candidates[0]?.page ?? doclingPage ?? undefined,
  };
}
