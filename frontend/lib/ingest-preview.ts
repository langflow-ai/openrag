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
