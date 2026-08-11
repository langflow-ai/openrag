import {
  type QueryKey,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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

/** Editable draft chunk (last-changes slot). */
export interface DraftChunk {
  chunk_id: string;
  page?: number | null;
  text: string;
  text_preview: string;
  char_count: number;
  dirty: boolean;
  docling_item_refs?: string[];
}

export interface ChunkDraftResponse {
  task_id: string;
  document_id: string;
  dirty: boolean;
  chunk_count: number;
  embedding_model?: string | null;
  chunks: DraftChunk[];
  expires_at?: number;
  committed?: boolean;
  modified_chunk_ids?: string[];
  removed_chunk_ids?: string[];
  filename?: string | null;
  chunks_truncated?: boolean;
  total_chunks_in_index?: number | null;
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
  chunkDraft: (taskId: string | null, filePath?: string | null) =>
    ["ingest-preview", "chunk-draft", taskId, filePath ?? null] as const,
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

async function mutatePreviewJson<T>(
  path: string,
  filePath: string | null | undefined,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(withFileParam(path, filePath), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) detail = body.error;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
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

/** Last-changes draft (seeded once index-proof is ready). */
export function useChunkDraftQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ingestPreviewQueryKeys.chunkDraft(taskId, filePath) as QueryKey,
      queryFn: () =>
        fetchPreviewJson<ChunkDraftResponse>(
          `/api/ingest/preview/${taskId}/chunks`,
          filePath,
        ),
      enabled: enabled && !!taskId,
      staleTime: 0,
      retry: 1,
      refetchOnWindowFocus: false,
    },
    queryClient,
  );
}

function useInvalidateChunkDraft() {
  const queryClient = useQueryClient();
  return (taskId: string, filePath?: string | null) => {
    void queryClient.invalidateQueries({
      queryKey: ingestPreviewQueryKeys.chunkDraft(taskId, filePath),
    });
    void queryClient.invalidateQueries({
      queryKey: ingestPreviewQueryKeys.indexProof(taskId, filePath),
    });
  };
}

export function usePatchDraftChunkMutation(
  taskId: string | null,
  filePath?: string | null,
) {
  const queryClient = useQueryClient();

  // Optimistic cache only — skip invalidate so Confirm flush does not
  // refetch mid-loop. Commit / revert / delete invalidate once.
  return useMutation({
    mutationFn: ({ chunkId, text }: { chunkId: string; text: string }) =>
      mutatePreviewJson<ChunkDraftResponse & { chunk: DraftChunk }>(
        `/api/ingest/preview/${taskId}/chunks/${encodeURIComponent(chunkId)}`,
        filePath,
        { method: "PATCH", body: JSON.stringify({ text }) },
      ),
    onSuccess: (data) => {
      if (!taskId) return;
      // PATCH returns the full session public payload (plus `chunk`).
      const { chunk, ...session } = data;
      queryClient.setQueryData(
        ingestPreviewQueryKeys.chunkDraft(taskId, filePath),
        (prev: ChunkDraftResponse | undefined) => {
          if (session.chunks?.length) {
            // Prefer the full server session. Guard prev so a PATCH that
            // lands before the draft query is cached still writes cleanly.
            return {
              ...(prev ?? {}),
              ...session,
              task_id: session.task_id ?? taskId,
            };
          }
          // Defensive fallback if an older server omits `chunks`.
          if (!prev) {
            return {
              task_id: taskId,
              document_id: session.document_id ?? "",
              dirty: session.dirty,
              chunk_count: session.chunk_count,
              embedding_model: session.embedding_model,
              expires_at: session.expires_at,
              chunks_truncated: session.chunks_truncated,
              total_chunks_in_index: session.total_chunks_in_index,
              chunks: chunk ? [chunk] : [],
            };
          }
          if (!chunk) {
            return {
              ...prev,
              dirty: session.dirty,
              chunk_count: session.chunk_count,
            };
          }
          return {
            ...prev,
            dirty: session.dirty,
            chunk_count: session.chunk_count,
            chunks: prev.chunks.map((c) =>
              c.chunk_id === chunk.chunk_id ? chunk : c,
            ),
          };
        },
      );
    },
  });
}

export function useDeleteDraftChunkMutation(
  taskId: string | null,
  filePath?: string | null,
) {
  const invalidate = useInvalidateChunkDraft();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ chunkId }: { chunkId: string }) =>
      mutatePreviewJson<ChunkDraftResponse>(
        `/api/ingest/preview/${taskId}/chunks/${encodeURIComponent(chunkId)}`,
        filePath,
        { method: "DELETE" },
      ),
    onSuccess: (data) => {
      if (!taskId) return;
      queryClient.setQueryData(
        ingestPreviewQueryKeys.chunkDraft(taskId, filePath),
        data,
      );
    },
    onSettled: () => {
      if (taskId) invalidate(taskId, filePath);
    },
  });
}

export function useRevertChunkDraftMutation(
  taskId: string | null,
  filePath?: string | null,
) {
  const invalidate = useInvalidateChunkDraft();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      mutatePreviewJson<ChunkDraftResponse>(
        `/api/ingest/preview/${taskId}/chunks/revert`,
        filePath,
        { method: "POST", body: "{}" },
      ),
    onSuccess: (data) => {
      if (!taskId) return;
      queryClient.setQueryData(
        ingestPreviewQueryKeys.chunkDraft(taskId, filePath),
        data,
      );
    },
    onSettled: () => {
      if (taskId) invalidate(taskId, filePath);
    },
  });
}

export function useCommitChunkDraftMutation(
  taskId: string | null,
  filePath?: string | null,
) {
  const invalidate = useInvalidateChunkDraft();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      mutatePreviewJson<ChunkDraftResponse>(
        `/api/ingest/preview/${taskId}/chunks/commit`,
        filePath,
        { method: "POST", body: "{}" },
      ),
    onSuccess: (data) => {
      if (!taskId) return;
      queryClient.setQueryData(
        ingestPreviewQueryKeys.chunkDraft(taskId, filePath),
        data,
      );
    },
    onSettled: () => {
      if (taskId) invalidate(taskId, filePath);
    },
  });
}
