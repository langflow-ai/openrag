import { useQuery, useQueryClient } from "@tanstack/react-query";

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

const MAX_PREVIEW_POLLS = 60;
const PREVIEW_POLL_INTERVAL_MS = 1500;

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

function usePreviewPollQuery<T>({
  queryKey,
  queryFn,
  enabled,
  staleTime,
  isDone,
  retry,
}: {
  queryKey: unknown[];
  queryFn: () => Promise<T>;
  enabled: boolean;
  staleTime: number;
  isDone: (data: T | undefined) => boolean;
  retry?: number;
}) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey,
      queryFn,
      enabled,
      staleTime,
      refetchInterval: (query) => {
        if (query.state.error) return false;
        if (isDone(query.state.data)) return false;
        if (query.state.dataUpdateCount >= MAX_PREVIEW_POLLS) return false;
        return PREVIEW_POLL_INTERVAL_MS;
      },
      retry: retry ?? false,
      refetchOnWindowFocus: false,
    },
    queryClient,
  );
}

/** Poll Docling layout cache; 404 while parsing means "not ready yet". */
export function useDoclingPreviewQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
) {
  return usePreviewPollQuery<DoclingPreviewResponse | null>({
    queryKey: ["ingest-preview", "docling", taskId, filePath ?? null],
    queryFn: () =>
      fetchPreviewJson<DoclingPreviewResponse>(
        `/api/ingest/preview/${taskId}/docling`,
        filePath,
        { notFoundAsNull: true },
      ),
    enabled: enabled && !!taskId,
    // Document JSON embeds page rasters — keep it cached for the session.
    staleTime: Number.POSITIVE_INFINITY,
    isDone: (data) => Boolean(data?.document),
    retry: 1,
  });
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
  return usePreviewPollQuery<IndexProofResponse>({
    queryKey: ["ingest-preview", "index-proof", taskId, filePath ?? null],
    queryFn: () =>
      fetchPreviewJson<IndexProofResponse>(
        `/api/ingest/preview/${taskId}/index-proof`,
        filePath,
      ),
    enabled: enabled && !!taskId,
    staleTime: 5_000,
    isDone: (data) => Boolean(data?.ready),
  });
}
