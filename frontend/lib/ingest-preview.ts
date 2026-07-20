/** Ingest preview helpers (OSS/SaaS UI gate; backend also requires the env flag). */

/**
 * Client-side gate for showing ingest-preview UI. OSS/SaaS only (never on_prem).
 * The backend still requires `OPENRAG_INGEST_PREVIEW_ENABLED=true` before
 * `preview_mode` is honored — uploads then report `preview_mode` in the 202 body.
 */
export function isIngestPreviewEnabled(
  runMode: string | null | undefined,
): boolean {
  return runMode === "oss" || runMode === "saas";
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

/** Map an indexed chunk page to a Docling `items` ref (`#/pages/N` is 1-based). */
export function chunkPageToDoclingRef(
  page: number,
  numbering: ChunkPageNumbering = "one-based",
): string {
  const doclingPage = numbering === "zero-based" ? page + 1 : page;
  return `#/pages/${doclingPage}`;
}

/** Inverse of `chunkPageToDoclingRef` for highlighting the matching chunk card. */
export function pageFromDoclingRef(
  highlightItems: string | undefined,
  numbering: ChunkPageNumbering = "one-based",
): number | null {
  if (!highlightItems?.startsWith("#/pages/")) return null;
  const n = Number(highlightItems.slice("#/pages/".length));
  if (!Number.isFinite(n)) return null;
  return numbering === "zero-based" ? n - 1 : n;
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
};

/**
 * Map an indexed chunk to Docling layout item refs by page + text overlap.
 * Falls back to page-level matching when no item scores well enough.
 */
export function matchChunkToDoclingItems(
  document: Record<string, unknown> | null | undefined,
  chunk: { page?: number | null; text: string },
  numbering: ChunkPageNumbering = "one-based",
): ChunkDoclingMatch | null {
  if (typeof chunk.page !== "number" && !chunk.text.trim()) {
    return null;
  }

  const pageFallback =
    typeof chunk.page === "number"
      ? {
          itemRefs: [] as string[],
          pageFallback: true,
        }
      : null;

  if (!document) return pageFallback;

  const doclingPage =
    typeof chunk.page === "number"
      ? numbering === "zero-based"
        ? chunk.page + 1
        : chunk.page
      : null;

  const candidates: Array<{ ref: string; score: number }> = [];
  const collections: Array<{ key: string; items: unknown }> = [
    { key: "texts", items: document.texts },
    { key: "tables", items: document.tables },
    { key: "pictures", items: document.pictures },
  ];

  for (const { key, items } of collections) {
    if (!Array.isArray(items)) continue;
    for (let i = 0; i < items.length; i += 1) {
      const item = items[i] as MatchableDoclingItem;
      const pages = itemPages(item);
      if (
        doclingPage != null &&
        pages.length > 0 &&
        !pages.includes(doclingPage)
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
      candidates.push({ ref, score });
    }
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
  };
}
