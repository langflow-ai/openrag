/**
 * Shared formatting helpers for file metadata (size + human-readable type
 * label). Centralised so the knowledge list, chunks "Original document" panel,
 * and file-browser dialog format the same values identically.
 */

/**
 * Format a byte count as a human-readable size (B/KB/MB/GB/TB).
 *
 * Uses bytes for sub-kilobyte files so small text/markdown documents render as
 * e.g. "412 B" instead of rounding down to a misleading "0 KB".
 */
export function formatFileSize(bytes?: number | null): string {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

const FILE_TYPE_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  // .txt and .md are both ingested as text/markdown (Langflow .txt->.md
  // workaround), so map both to a sensible label here.
  "text/markdown": "Markdown",
  "text/plain": "Text",
  "text/csv": "CSV",
  "text/html": "HTML",
  "application/json": "JSON",
  "application/msword": "Word Document",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    "Word Document",
  "application/vnd.ms-excel": "Excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
  "application/vnd.ms-powerpoint": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation":
    "PowerPoint",
};

/**
 * Map a mimetype to a short human-readable type label. Falls back to a generic
 * group label (Image/Audio/Video/Text) before "Unknown".
 */
export function getFileTypeLabel(mimetype?: string | null): string {
  if (!mimetype) return "Unknown";
  const normalized = mimetype.toLowerCase();
  if (normalized in FILE_TYPE_LABELS) return FILE_TYPE_LABELS[normalized];
  if (normalized.startsWith("image/")) return "Image";
  if (normalized.startsWith("audio/")) return "Audio";
  if (normalized.startsWith("video/")) return "Video";
  if (normalized.startsWith("text/")) return "Text";
  return "Unknown";
}
