import { type QueryKey, useQuery, useQueryClient } from "@tanstack/react-query";

export interface DoclingPreviewStats {
  page_count: number;
  text_count: number;
  table_count: number;
  picture_count: number;
}

export interface DoclingPreviewResponse {
  task_id: string;
  document: Record<string, unknown>;
  stats: DoclingPreviewStats;
  expires_at: number;
  document_id?: string;
  file_path?: string;
  filename?: string;
}

/** A single indexed chunk from the preview index-proof endpoint. */
export interface IndexProofChunk {
  chunk_id: string;
  page?: number | null;
  text_preview: string;
  char_count: number;
}

/** Response of GET /ingest/preview/{task_id}/index-proof. */
export interface IndexProofResponse {
  task_id: string;
  ready: boolean;
  phase?: string;
  chunk_count: number;
  chunks_returned?: number;
  chunks_truncated?: boolean;
  embedding_model?: string;
  embedding_dimensions?: number;
  chunks: IndexProofChunk[];
  document_id?: string | null;
}

/**
 * Index-proof can flip to ready without a task phase change, so it still
 * polls. Docling preview does not — it refetches on task phase / retry.
 */
const INDEX_PROOF_POLL_INTERVAL_MS = 1500;
const INDEX_PROOF_MAX_POLLS = 60;

export const ingestPreviewQueryKeys = {
  docling: (taskId: string | null, filePath?: string | null) =>
    ["ingest-preview", "docling", taskId, filePath ?? null] as const,
  indexProof: (taskId: string | null, filePath?: string | null) =>
    ["ingest-preview", "index-proof", taskId, filePath ?? null] as const,
};

function withFileParam(path: string, filePath?: string | null): string {
  return filePath ? `${path}?file=${encodeURIComponent(filePath)}` : path;
}

async function fetchPreviewJson<T>(
  path: string,
  filePath: string | null | undefined,
  options: { notFoundAsNull: true },
): Promise<T | null>;
async function fetchPreviewJson<T>(
  path: string,
  filePath?: string | null,
  options?: { notFoundAsNull?: false },
): Promise<T>;
async function fetchPreviewJson<T>(
  path: string,
  filePath?: string | null,
  options?: { notFoundAsNull?: boolean },
): Promise<T | null> {
  const response = await fetch(withFileParam(path, filePath));
  if (options?.notFoundAsNull && response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Preview unavailable (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/**
 * Fetch Docling layout cache once. 404 → null ("not cached yet").
 * No interval polling — callers refetch when the ingest task phase advances
 * or when the user retries.
 */
export function useDoclingPreviewQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ingestPreviewQueryKeys.docling(taskId, filePath),
      queryFn: () =>
        fetchPreviewJson<DoclingPreviewResponse>(
          `/api/ingest/preview/${taskId}/docling`,
          filePath,
          { notFoundAsNull: true },
        ),
      enabled: enabled && !!taskId,
      // Keep large documents cached once loaded; null/404 stays stale so a
      // later phase-driven refetch can replace it.
      staleTime: (q) => (q.state.data?.document ? Number.POSITIVE_INFINITY : 0),
      retry: 1,
      refetchOnWindowFocus: false,
    },
    queryClient,
  );
}

/**
 * Poll index-proof until chunks land (keyed by task + file).
 *
 * "Not ready yet" is HTTP 200 with `ready: false` — keep polling via isDone.
 * 404 (missing task/file, preview disabled) throws and stops polling; that is
 * intentional, unlike Docling preview where 404 means "still parsing".
 */
export function useIndexProofQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ingestPreviewQueryKeys.indexProof(taskId, filePath) as QueryKey,
      queryFn: () =>
        fetchPreviewJson<IndexProofResponse>(
          `/api/ingest/preview/${taskId}/index-proof`,
          filePath,
        ),
      enabled: enabled && !!taskId,
      staleTime: 5_000,
      refetchInterval: (query) => {
        if (query.state.error) return false;
        if (query.state.data?.ready) return false;
        if (query.state.dataUpdateCount >= INDEX_PROOF_MAX_POLLS) return false;
        return INDEX_PROOF_POLL_INTERVAL_MS;
      },
      retry: false,
      refetchOnWindowFocus: false,
    },
    queryClient,
  );
}
