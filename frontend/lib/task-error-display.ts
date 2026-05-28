// Will update when backend is ready (error_summary, failing_step, component_cause).

export const FILE_ERROR_MAX_LINE_LENGTH = 80;

export type TaskErrorComponentCause = "OpenSearch" | "Docling" | "Langflow";

const COMPONENT_CAUSES: ReadonlyArray<{
  keyword: string;
  label: TaskErrorComponentCause;
}> = [
  { keyword: "opensearch", label: "OpenSearch" },
  { keyword: "docling", label: "Docling" },
  { keyword: "langflow", label: "Langflow" },
];

export interface FileTaskErrorDisplay {
  line: string;
  componentCause?: TaskErrorComponentCause;
}

function normalizeErrorText(raw: string): string {
  return raw.replace(/\s+/g, " ").trim();
}

function stripNoisePrefixes(text: string): string {
  return text
    .replace(/^Error running graph:\s*/i, "")
    .replace(/^Error building Component [^:]+:\s*/i, "")
    .trim();
}

function truncateLine(
  text: string,
  maxLength = FILE_ERROR_MAX_LINE_LENGTH,
): string {
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trimEnd()}…`;
}

/** Prefer a short clause from long, nested error strings. */
function extractReadableLine(text: string): string {
  const beforeCausedBy = text.split(/\s+caused by:/i)[0]?.trim() ?? text;

  if (beforeCausedBy.length <= FILE_ERROR_MAX_LINE_LENGTH) {
    return beforeCausedBy;
  }

  const colonParts = beforeCausedBy.split(":");
  const lastClause = colonParts[colonParts.length - 1]?.trim();
  if (
    lastClause &&
    lastClause.length >= 10 &&
    lastClause.length <= FILE_ERROR_MAX_LINE_LENGTH
  ) {
    return lastClause;
  }

  return beforeCausedBy;
}

export function detectComponentCause(
  raw: string,
): TaskErrorComponentCause | undefined {
  const lower = raw.toLowerCase();
  for (const { keyword, label } of COMPONENT_CAUSES) {
    if (lower.includes(keyword)) {
      return label;
    }
  }
  return undefined;
}

export function displayFileTaskError(
  raw: string | undefined | null,
): FileTaskErrorDisplay {
  if (!raw?.trim()) {
    return { line: "Unknown error" };
  }

  const normalized = normalizeErrorText(raw);
  const componentCause = detectComponentCause(normalized);

  let line = stripNoisePrefixes(normalized);
  line = truncateLine(extractReadableLine(line));

  if (!line) {
    line = "Unknown error";
  }

  return componentCause ? { line, componentCause } : { line };
}
