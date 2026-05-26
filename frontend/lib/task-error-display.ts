// Prefer API `failure_phase` for failed-step inference; `component_cause` may follow later.

import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";

export const FILE_ERROR_MAX_LINE_LENGTH = 80;

export type TaskErrorComponentCause = "OpenSearch" | "Docling" | "Langflow";

export type IngestionPipelineStepId =
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing";

export interface IngestionPipelineStep {
  id: IngestionPipelineStepId;
  label: string;
  status: "completed" | "failed";
}

export interface TaskFileIngestionFailureAnalysis {
  resolvedError: string;
  failedStep: IngestionPipelineStepId;
  pipelineSteps: IngestionPipelineStep[];
  rowStatusLabel: string;
  failureSummary: string;
  componentCause?: TaskErrorComponentCause;
  componentTags: string[];
  /** Short line for compact panels (truncated). */
  summaryLine: string;
}

const PIPELINE_STEP_ORDER: IngestionPipelineStepId[] = [
  "parsing",
  "chunking",
  "embedding",
  "indexing",
];

const PIPELINE_STEP_LABELS: Record<IngestionPipelineStepId, string> = {
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  indexing: "Indexing",
};

const COMPONENT_CAUSES: ReadonlyArray<{
  keyword: RegExp;
  label: TaskErrorComponentCause;
}> = [
  { keyword: /opensearch/i, label: "OpenSearch" },
  { keyword: /docling/i, label: "Docling" },
  { keyword: /langflow/i, label: "Langflow" },
];

const STEP_ERROR_SIGNALS: Record<
  IngestionPipelineStepId,
  ReadonlyArray<RegExp>
> = {
  parsing: [/docling/i, /\bpars(e|ing)\b/i, /convert/i, /ocr/i],
  chunking: [/chunk/i, /\bsplit/i, /segment/i],
  embedding: [/embed/i, /\bvector/i, /dimension/i],
  indexing: [/opensearch/i, /\bindex/i, /mapping/i, /schema/i],
};

const ISSUE_TYPE_SIGNALS: ReadonlyArray<{ pattern: RegExp; label: string }> = [
  {
    pattern: /schema|mapping|does not match.*index/i,
    label: "pipeline configuration issue",
  },
  { pattern: /timeout|timed?\s*out/i, label: "timeout" },
  {
    pattern: /unauthorized|forbidden|403|401|permission/i,
    label: "access issue",
  },
  { pattern: /connection|unreachable|network/i, label: "connectivity issue" },
  { pattern: /embed|model|dimension/i, label: "embedding configuration issue" },
  { pattern: /quota|limit|rate/i, label: "rate limit" },
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
  for (const { keyword, label } of COMPONENT_CAUSES) {
    if (keyword.test(raw)) {
      return label;
    }
  }
  return undefined;
}

function scorePipelineStepsFromError(
  error: string,
): Record<IngestionPipelineStepId, number> {
  const scores: Record<IngestionPipelineStepId, number> = {
    parsing: 0,
    chunking: 0,
    embedding: 0,
    indexing: 0,
  };
  for (const step of PIPELINE_STEP_ORDER) {
    for (const pattern of STEP_ERROR_SIGNALS[step]) {
      if (pattern.test(error)) {
        scores[step] += 1;
      }
    }
  }
  return scores;
}

function pickFailedStepFromErrorScores(
  scores: Record<IngestionPipelineStepId, number>,
): IngestionPipelineStepId | null {
  const maxScore = Math.max(...PIPELINE_STEP_ORDER.map((step) => scores[step]));
  if (maxScore === 0) {
    return null;
  }
  const matching = PIPELINE_STEP_ORDER.filter(
    (step) => scores[step] === maxScore,
  );
  return matching[matching.length - 1] ?? null;
}

function inferFailedStepFromPhase(
  fileInfo: TaskFileEntry,
): IngestionPipelineStepId | null {
  const phase =
    typeof fileInfo.phase === "string" ? fileInfo.phase.toLowerCase() : "";
  const doclingStatus =
    typeof fileInfo.docling_status === "string"
      ? fileInfo.docling_status.toLowerCase()
      : "";

  if (phase === "docling" || doclingStatus === "failed") {
    return "parsing";
  }
  if (phase === "langflow") {
    return "embedding";
  }
  if (phase === "complete") {
    return "indexing";
  }
  return null;
}

export function inferFailedPipelineStep(
  fileInfo: TaskFileEntry,
  rawError: string,
): IngestionPipelineStepId {
  const normalized = normalizeErrorText(rawError);
  const fromError = pickFailedStepFromErrorScores(
    scorePipelineStepsFromError(normalized),
  );
  if (fromError) {
    return fromError;
  }
  return inferFailedStepFromPhase(fileInfo) ?? "embedding";
}

function getPhaseMinimumFailedIndex(phase: string): number {
  if (phase === "complete") {
    return PIPELINE_STEP_ORDER.indexOf("indexing");
  }
  if (phase === "langflow") {
    return PIPELINE_STEP_ORDER.indexOf("embedding");
  }
  return 0;
}

export function buildIngestionPipelineSteps(
  failedStep: IngestionPipelineStepId,
  fileInfo: TaskFileEntry,
): IngestionPipelineStep[] {
  const phase =
    typeof fileInfo.phase === "string" ? fileInfo.phase.toLowerCase() : "";

  const failedIndex = PIPELINE_STEP_ORDER.indexOf(failedStep);
  const lastIndex = Math.max(failedIndex, getPhaseMinimumFailedIndex(phase));

  return PIPELINE_STEP_ORDER.slice(0, lastIndex + 1).map((id, index) => ({
    id,
    label: PIPELINE_STEP_LABELS[id],
    status: index < lastIndex ? "completed" : "failed",
  }));
}

function inferIssueType(error: string): string | null {
  for (const { pattern, label } of ISSUE_TYPE_SIGNALS) {
    if (pattern.test(error)) {
      return label;
    }
  }
  return null;
}

export function buildFailureSummary(
  failedStep: IngestionPipelineStepId,
  error: string,
): string {
  const stepLabel = PIPELINE_STEP_LABELS[failedStep].toLowerCase();
  const issueType = inferIssueType(error);
  return issueType
    ? `Failed at ${stepLabel} · ${issueType}`
    : `Failed at ${stepLabel}`;
}

export function buildRowStatusLabel(
  failedStep: IngestionPipelineStepId,
): string {
  return `${PIPELINE_STEP_LABELS[failedStep]} issue`;
}

export function buildComponentTags(
  error: string,
  componentCause?: TaskErrorComponentCause,
): string[] {
  const tags: string[] = [];
  if (componentCause) {
    tags.push(componentCause);
  }
  if (/mapping/i.test(error) && !tags.includes("Mapping")) {
    tags.push("Mapping");
  }
  if (/schema/i.test(error) && !tags.includes("Schema")) {
    tags.push("Schema");
  }
  return tags;
}

export function resolveTaskFileError(
  fileInfo: TaskFileEntry,
  taskError?: string,
): string {
  if (typeof fileInfo.error === "string" && fileInfo.error.trim()) {
    return fileInfo.error.trim();
  }
  if (typeof taskError === "string" && taskError.trim()) {
    return taskError.trim();
  }
  return "Unknown error";
}

export function analyzeTaskFileIngestionFailure(
  fileInfo: TaskFileEntry,
  taskError?: string,
): TaskFileIngestionFailureAnalysis {
  const resolvedError = resolveTaskFileError(fileInfo, taskError);
  const normalized = normalizeErrorText(resolvedError);
  const componentCause = detectComponentCause(normalized);
  const failedStep = inferFailedPipelineStep(fileInfo, normalized);
  const pipelineSteps = buildIngestionPipelineSteps(failedStep, fileInfo);
  const summaryLine = truncateLine(
    extractReadableLine(stripNoisePrefixes(normalized)),
  );

  return {
    resolvedError,
    failedStep,
    pipelineSteps,
    rowStatusLabel: buildRowStatusLabel(failedStep),
    failureSummary: buildFailureSummary(failedStep, normalized),
    componentCause,
    componentTags: buildComponentTags(normalized, componentCause),
    summaryLine,
  };
}

/** @deprecated Use analyzeTaskFileIngestionFailure */
export function getIngestionPipelineSteps(
  raw: string | undefined | null,
  componentCause?: TaskErrorComponentCause,
  fileInfo?: TaskFileEntry,
): IngestionPipelineStep[] {
  const resolved = (raw ?? "").trim() || "Unknown error";
  const failedStep = fileInfo
    ? inferFailedPipelineStep(fileInfo, resolved)
    : (pickFailedStepFromErrorScores(scorePipelineStepsFromError(resolved)) ??
      (componentCause === "Docling"
        ? "parsing"
        : componentCause === "Langflow"
          ? "embedding"
          : componentCause === "OpenSearch"
            ? "indexing"
            : "embedding"));
  return buildIngestionPipelineSteps(
    failedStep,
    fileInfo ??
      ({ phase: undefined, docling_status: undefined } as TaskFileEntry),
  );
}

export function displayFileTaskError(
  raw: string | undefined | null,
  fileInfo?: TaskFileEntry,
  taskError?: string,
): FileTaskErrorDisplay {
  if (fileInfo) {
    const analysis = analyzeTaskFileIngestionFailure(fileInfo, taskError);
    return {
      line: analysis.summaryLine,
      componentCause: analysis.componentCause,
    };
  }

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
