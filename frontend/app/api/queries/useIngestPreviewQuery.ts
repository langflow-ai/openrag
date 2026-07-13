import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

interface DoclingPreviewStats {
  page_count: number;
  text_count: number;
  table_count: number;
  picture_count: number;
}

interface DoclingPreviewResponse {
  task_id: string;
  document: Record<string, unknown>;
  stats: DoclingPreviewStats;
  expires_at: number;
  document_id?: string;
  file_path?: string;
  filename?: string;
}

interface IndexProofChunk {
  chunk_id: string;
  page?: number;
  text_preview: string;
  char_count: number;
}

interface IndexProofResponse {
  task_id: string;
  ready: boolean;
  phase?: string;
  chunk_count: number;
  embedding_model?: string;
  embedding_dimensions?: number;
  chunks: IndexProofChunk[];
  document_id?: string;
}

// Stop polling after this many attempts so a file that never produces a preview
// (un-cacheable format, expired/failed task, cap reached) can't poll forever.
// At 1.5s/poll this is ~90s, comfortably longer than a single-file parse.
const MAX_PREVIEW_POLLS = 60;
const PREVIEW_POLL_INTERVAL_MS = 1500;

function withFileParam(path: string, filePath?: string | null): string {
  return filePath ? `${path}?file=${encodeURIComponent(filePath)}` : path;
}

async function fetchDoclingPreview(
  taskId: string,
  filePath?: string | null,
): Promise<DoclingPreviewResponse | null> {
  const response = await fetch(
    withFileParam(`/api/ingest/preview/${taskId}/docling`, filePath),
  );
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Parse preview unavailable (${response.status})`);
  }
  return response.json();
}

async function fetchIndexProof(
  taskId: string,
  filePath?: string | null,
): Promise<IndexProofResponse> {
  const response = await fetch(
    withFileParam(`/api/ingest/preview/${taskId}/index-proof`, filePath),
  );
  if (!response.ok) {
    throw new Error(`Index proof unavailable (${response.status})`);
  }
  return response.json();
}

export function useDoclingPreviewQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
  options?: Omit<
    UseQueryOptions<DoclingPreviewResponse | null>,
    "queryKey" | "queryFn" | "enabled"
  >,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["ingest-preview", "docling", taskId, filePath ?? null],
      queryFn: () => fetchDoclingPreview(taskId as string, filePath),
      enabled: enabled && !!taskId,
      refetchInterval: (query) => {
        if (query.state.data?.document) return false;
        if (!(enabled && taskId)) return false;
        if (query.state.dataUpdateCount >= MAX_PREVIEW_POLLS) return false;
        return PREVIEW_POLL_INTERVAL_MS;
      },
      retry: 1,
      refetchOnWindowFocus: false,
      ...options,
    },
    queryClient,
  );
}

export function useIndexProofQuery(
  taskId: string | null,
  enabled: boolean,
  filePath?: string | null,
  options?: Omit<
    UseQueryOptions<IndexProofResponse>,
    "queryKey" | "queryFn" | "enabled"
  >,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: ["ingest-preview", "index-proof", taskId, filePath ?? null],
      queryFn: () => fetchIndexProof(taskId as string, filePath),
      enabled: enabled && !!taskId,
      refetchInterval: (query) => {
        if (query.state.data?.ready) return false;
        if (query.state.dataUpdateCount >= MAX_PREVIEW_POLLS) return false;
        return PREVIEW_POLL_INTERVAL_MS;
      },
      refetchOnWindowFocus: false,
      ...options,
    },
    queryClient,
  );
}
