import type {
  TaskFailureComponent,
  TaskFailurePhase,
  TaskFileEntry,
} from "@/app/api/queries/useGetTasksQuery";

export const FILE_ERROR_MAX_LINE_LENGTH = 80;

export type TaskErrorComponentCause =
  | "OpenSearch"
  | "Docling"
  | "Langflow"
  | "OpenRAG";

export type TaskPipelineStepId =
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "file_validation"
  | "cancelled"
  | "unknown";

export interface IngestionPipelineStep {
  id: TaskPipelineStepId;
  label: string;
  status: "completed" | "failed";
}

export interface TaskFileIngestionFailureAnalysis {
  resolvedError: string;
  failedStep: TaskPipelineStepId;
  pipelineSteps: IngestionPipelineStep[];
  rowStatusLabel: string;
  failureSummary: string;
  componentCause?: TaskErrorComponentCause;
  componentTags: string[];
  summaryLine: string;
}

const PIPELINE_STEP_ORDER: TaskPipelineStepId[] = [
  "parsing",
  "chunking",
  "embedding",
  "indexing",
];

const PIPELINE_STEP_LABELS: Record<TaskPipelineStepId, string> = {
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  indexing: "Indexing",
  file_validation: "File validation",
  cancelled: "Cancelled",
  unknown: "Ingestion",
};

const COMPONENT_LABELS: Record<TaskFailureComponent, TaskErrorComponentCause> =
  {
    docling: "Docling",
    openrag: "OpenRAG",
    langflow: "Langflow",
    opensearch: "OpenSearch",
  };

function truncateLine(
  text: string,
  maxLength = FILE_ERROR_MAX_LINE_LENGTH,
): string {
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, maxLength - 1).trimEnd()}…`;
}

export function formatApiComponent(
  component?: TaskFailureComponent,
): TaskErrorComponentCause | undefined {
  if (!component) {
    return undefined;
  }
  return COMPONENT_LABELS[component];
}

export function normalizeFailurePhase(
  phase?: string,
): TaskPipelineStepId | undefined {
  if (!phase) {
    return undefined;
  }
  if (phase in PIPELINE_STEP_LABELS) {
    return phase as TaskPipelineStepId;
  }
  return undefined;
}

export function buildRowStatusLabel(failedStep: TaskPipelineStepId): string {
  if (failedStep === "cancelled") {
    return "Cancelled";
  }
  if (failedStep === "file_validation") {
    return "File validation issue";
  }
  if (failedStep === "unknown") {
    return "Failed";
  }
  return `${PIPELINE_STEP_LABELS[failedStep]} issue`;
}

function buildFailureSummary(failedStep: TaskPipelineStepId): string {
  if (failedStep === "cancelled") {
    return "Cancelled";
  }
  return `Failed at ${PIPELINE_STEP_LABELS[failedStep].toLowerCase()}`;
}

function buildPipelineStepsFromFailurePhase(
  failurePhase: TaskPipelineStepId,
): IngestionPipelineStep[] {
  if (
    failurePhase === "file_validation" ||
    failurePhase === "cancelled" ||
    failurePhase === "unknown"
  ) {
    return [
      {
        id: failurePhase,
        label: PIPELINE_STEP_LABELS[failurePhase],
        status: "failed",
      },
    ];
  }

  const failedIndex = PIPELINE_STEP_ORDER.indexOf(failurePhase);
  if (failedIndex < 0) {
    return [
      { id: "unknown", label: PIPELINE_STEP_LABELS.unknown, status: "failed" },
    ];
  }

  return PIPELINE_STEP_ORDER.slice(0, failedIndex + 1).map((id, index) => ({
    id,
    label: PIPELINE_STEP_LABELS[id],
    status: index < failedIndex ? "completed" : "failed",
  }));
}

export function resolveTaskFileError(
  fileInfo: TaskFileEntry,
  taskError?: string,
): string {
  if (
    fileInfo.result &&
    typeof fileInfo.result === "object" &&
    "warning" in fileInfo.result &&
    typeof fileInfo.result.warning === "string" &&
    fileInfo.result.warning.trim()
  ) {
    return fileInfo.result.warning.trim();
  }
  if (typeof fileInfo.user_facing_message === "string") {
    const message = fileInfo.user_facing_message.trim();
    if (message) {
      return message;
    }
  }
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
  const failedStep = normalizeFailurePhase(fileInfo.failure_phase) ?? "unknown";
  const pipelineSteps = buildPipelineStepsFromFailurePhase(failedStep);
  const componentCause = formatApiComponent(fileInfo.component);
  const componentTags = componentCause ? [componentCause] : [];

  return {
    resolvedError,
    failedStep,
    pipelineSteps,
    rowStatusLabel: buildRowStatusLabel(failedStep),
    failureSummary: buildFailureSummary(failedStep),
    componentCause,
    componentTags,
    summaryLine: truncateLine(resolvedError),
  };
}
