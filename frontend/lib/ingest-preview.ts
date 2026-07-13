/** Ingest layout preview helpers (OSS-only feature). */

export function isIngestPreviewEnabled(
  runMode: string | null | undefined,
): boolean {
  return runMode === "oss";
}

type ChunkPageNumbering = "zero-based" | "one-based";

export function inferChunkPageNumbering(
  chunks: Array<{ page?: number | null }>,
): ChunkPageNumbering {
  const pages = chunks
    .map((chunk) => chunk.page)
    .filter((page): page is number => typeof page === "number");
  if (pages.length === 0) {
    return "one-based";
  }
  return Math.min(...pages) === 0 ? "zero-based" : "one-based";
}

/** Map an indexed chunk page to a Docling `items` ref (`#/pages/N` is 1-based). */
export function chunkPageToDoclingRef(
  page: number,
  numbering: ChunkPageNumbering = "one-based",
): string {
  const doclingPage = numbering === "zero-based" ? page + 1 : page;
  return `#/pages/${doclingPage}`;
}
