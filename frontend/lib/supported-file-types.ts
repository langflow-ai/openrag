/**
 * Local / chat file picker + folder ingest filter — single source of truth.
 * Only extensions verified to ingest successfully in the Langflow pipeline.
 * If modified, update docs (docs/docs/core-components/ingestion.mdx).
 *
 * documents: txt, md, html, htm, adoc, asciidoc, asc, pdf, docx
 * spreadsheets: csv, xlsx
 * presentations: pptx
 * images (OCR required): bmp, jpeg, jpg, png, tiff, webp
 */
export type SupportedFileTypes = Record<string, string[]>;

export const BASE_SUPPORTED_FILE_TYPES: SupportedFileTypes = {
  "text/plain": [".txt"],
  "text/markdown": [".md"],
  "text/html": [".html", ".htm"],
  "text/asciidoc": [".adoc", ".asciidoc", ".asc"],
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
    ".docx",
  ],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
    ".xlsx",
  ],
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": [
    ".pptx",
  ],
  "text/csv": [".csv"],
};

/** Raster image formats that require OCR to produce text (matches backend). */
export const OCR_SUPPORTED_FILE_TYPES: SupportedFileTypes = {
  "image/bmp": [".bmp"],
  "image/jpeg": [".jpeg", ".jpg"],
  "image/png": [".png"],
  "image/tiff": [".tiff"],
  "image/webp": [".webp"],
};

export function getSupportedFileTypes(ocrEnabled = false): SupportedFileTypes {
  if (!ocrEnabled) return BASE_SUPPORTED_FILE_TYPES;
  return { ...BASE_SUPPORTED_FILE_TYPES, ...OCR_SUPPORTED_FILE_TYPES };
}

export function getSupportedExtensions(ocrEnabled = false): string[] {
  return Object.values(getSupportedFileTypes(ocrEnabled)).flat();
}

/** Default (OCR off) — kept for backward compatibility. */
export const SUPPORTED_FILE_TYPES = BASE_SUPPORTED_FILE_TYPES;

export const SUPPORTED_EXTENSIONS = getSupportedExtensions(false);
