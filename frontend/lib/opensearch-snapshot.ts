/**
 * Types, request helper and pure helpers for the OpenSearch snapshot import
 * connector. The browser reaches the backend through the catch-all proxy, so
 * backend route `/connectors/opensearch_snapshot/...` is `/api/connectors/...`.
 */

export const SNAPSHOT_API = "/api/connectors/opensearch_snapshot";

export interface SnapshotStatus {
  enabled: boolean;
  reason: string | null;
  staging_type: string;
  security_managed: boolean;
  private_supported: boolean;
}

export interface SnapshotSource {
  id: string;
  name: string;
  endpoint_url: string | null;
  region: string;
  bucket: string;
  prefix: string;
  path_style: boolean;
  verify_tls: boolean;
  has_credentials: boolean;
  created_at: string;
  updated_at: string;
}

export interface SnapshotSourceInput {
  name: string;
  /** `null` clears a stored endpoint on update. */
  endpoint_url?: string | null;
  region: string;
  bucket: string;
  prefix: string;
  /** Omitted on update = keep the stored key. */
  access_key?: string;
  secret_key?: string;
  path_style: boolean;
  verify_tls: boolean;
}

export interface SnapshotIndexSummary {
  name: string;
  /** Absent/0 when the backend could not determine it. */
  size_bytes?: number | null;
}

export interface SnapshotSummary {
  name: string;
  uuid: string;
  state: string;
  version: string;
  indices: SnapshotIndexSummary[];
}

export interface SnapshotListing {
  repository_generation: number;
  snapshots: SnapshotSummary[];
}

export interface PreflightIssue {
  code: string;
  message: string;
  index?: string | null;
}

export interface AnalyserFileRef {
  index: string;
  setting: string;
  path: string;
  inline_setting: string;
}

export interface PreflightResult {
  ok: boolean;
  blockers: PreflightIssue[];
  warnings: PreflightIssue[];
  analyser_files: AnalyserFileRef[];
  staged_bytes: number;
  restored_bytes: number;
  indices: { name: string; created_version: string; doc_count?: number }[];
}

export interface AnalyserFileUpload {
  index: string;
  setting: string;
  content: string;
}

export interface DatasetField {
  name: string;
  type: string;
  dims?: number | null;
}

export interface DatasetVectorField extends DatasetField {
  engine?: string | null;
}

export interface DatasetFieldMap {
  text_fields?: string[];
  title_field?: string | null;
  url_field?: string | null;
  [key: string]: unknown;
}

export interface DatasetRetrieval {
  mode?: "lexical" | "hybrid";
  vector_field?: string;
  provider?: string;
  model?: string;
  dims?: number | null;
  [key: string]: unknown;
}

export interface SnapshotDataset {
  id: string;
  ordinal: number;
  source_index: string;
  index_alias: string;
  display_name: string;
  description: string;
  doc_count: number | null;
  field_map: DatasetFieldMap;
  retrieval: DatasetRetrieval;
  fields: DatasetField[];
  vector_fields: DatasetVectorField[];
  /** Qualified `provider:model` ids. */
  available_models: string[];
}

export type SnapshotImportStatus =
  | "staging"
  | "restoring"
  | "review"
  | "active"
  | "failed"
  | "deleting";

export type SnapshotJobState =
  | "idle"
  | "queued"
  | "running"
  | "failed"
  | "cancelled"
  // Interrupted job being reconciled by the backend after a restart.
  | "recovery";

export interface SnapshotImport {
  id: string;
  slug: string;
  name: string;
  source_id: string;
  snapshot_name: string;
  snapshot_uuid: string;
  written_by_version: string;
  source_indices: string[];
  staged_bytes: number;
  status: SnapshotImportStatus;
  generation: number;
  shared: boolean;
  is_owner: boolean;
  job: {
    state: SnapshotJobState;
    kind: "import" | "reimport" | "delete" | null;
    error: string | null;
    task_id: string | null;
  };
  role_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  datasets: SnapshotDataset[];
}

export interface SnapshotDatasetListing {
  id: string;
  import_id: string;
  import_name: string;
  display_name: string;
  description: string;
  source_index: string;
  shared: boolean;
  is_owner: boolean;
}

export interface StartImportRequest {
  source_id: string;
  snapshot: string;
  indices: string[];
  name: string;
  shared: boolean;
  analyser_files: AnalyserFileUpload[];
}

export interface SnapshotImportAccepted {
  import: SnapshotImport;
  task_id: string;
}

/** A non-2xx backend answer, with the structured fields the UI reacts to. */
export class SnapshotApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly blockers: PreflightIssue[];
  readonly roleJson: Record<string, unknown> | null;

  constructor(
    status: number,
    message: string,
    code: string | null,
    blockers: PreflightIssue[],
    roleJson: Record<string, unknown> | null,
  ) {
    super(message);
    this.name = "SnapshotApiError";
    this.status = status;
    this.code = code;
    this.blockers = blockers;
    this.roleJson = roleJson;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function describeDetailList(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((entry) => asRecord(entry)?.msg ?? entry)
    .filter((entry): entry is string => typeof entry === "string");
  return messages.length > 0 ? messages.join("; ") : null;
}

function toApiError(status: number, body: unknown, fallback: string) {
  const root = asRecord(body);
  // FastAPI wraps `HTTPException(detail={...})` as `{detail: {...}}`.
  const payload = asRecord(root?.detail) ?? root;
  const message =
    [payload?.error, payload?.message, root?.error, root?.message, root?.detail]
      .concat(describeDetailList(root?.detail))
      .find((value): value is string => typeof value === "string" && !!value) ??
    fallback;
  const code =
    typeof payload?.code === "string"
      ? payload.code
      : typeof root?.code === "string"
        ? root.code
        : null;
  const blockers = Array.isArray(payload?.blockers)
    ? (payload.blockers as PreflightIssue[])
    : [];
  return new SnapshotApiError(
    status,
    message,
    code,
    blockers,
    asRecord(payload?.role_json),
  );
}

export async function snapshotRequest<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PATCH" | "DELETE";
    body?: unknown;
    signal?: AbortSignal;
    fallbackError?: string;
  } = {},
): Promise<T> {
  const { method = "GET", body, signal, fallbackError } = options;
  const response = await fetch(`${SNAPSHOT_API}${path}`, {
    method,
    signal,
    ...(body !== undefined && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  });
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw toApiError(
      response.status,
      data,
      fallbackError ?? `Request failed (${response.status})`,
    );
  }
  return data as T;
}

export const snapshotKeys = {
  all: ["opensearch-snapshot"] as const,
  status: ["opensearch-snapshot", "status"] as const,
  sources: ["opensearch-snapshot", "sources"] as const,
  snapshots: (sourceId: string) =>
    ["opensearch-snapshot", "sources", sourceId, "snapshots"] as const,
  imports: ["opensearch-snapshot", "imports"] as const,
  import: (importId: string) =>
    ["opensearch-snapshot", "imports", importId] as const,
  datasets: ["opensearch-snapshot", "datasets"] as const,
};

/** True while the backend is still working on an import (poll until false). */
export function isImportBusy(imp: SnapshotImport): boolean {
  if (imp.status === "staging" || imp.status === "restoring") {
    return imp.job.state === "queued" || imp.job.state === "running";
  }
  // A failed/cancelled cleanup job is terminal: stop polling, allow a retry.
  if (imp.status === "deleting") {
    return imp.job.state !== "failed" && imp.job.state !== "cancelled";
  }
  return imp.job.state === "queued" || imp.job.state === "running";
}

/**
 * True while the import can still change without user action: busy, or being
 * recovered by the backend after a restart. Recovery leaves controls enabled
 * (owners may unshare or retry) but must keep the view refreshing.
 */
export function shouldPollImport(imp: SnapshotImport): boolean {
  return isImportBusy(imp) || imp.job.state === "recovery";
}

export function formatBytes(bytes: number | null | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes <= 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}
