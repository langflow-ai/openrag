import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export interface RemoteFile {
  id: string;
  name: string;
  bucket: string;
  key: string;
  size: number;
  modified_time: string;
  is_ingested: boolean;
  /** Ingested, but the source version is newer than what we indexed. Such files
   * stay selectable (to re-ingest the newer version) while unchanged ingested
   * files are disabled. */
  is_stale: boolean;
}

export interface BrowseConnectionFilesParams {
  connectorType: string;
  connectionId: string;
  bucket?: string;
  /**
   * Currently unused. The FileBrowserDialog filters the fetched list in-memory
   * (client-side) instead of sending this to the backend, because the existing
   * server-side `search` is deficient: it doesn't filter directly at the
   * connector level — it fetches the capped blob list (maxFiles) and then
   * post-filters it in memory, so it can't match files beyond the cap and
   * re-fetches the whole list per query. Passing it would also remount the
   * query's loading state on every keystroke.
   * TODO: implement true server-side filtering at the connector level (push the
   * search term into the connector's list call), then reinstate this param.
   */
  search?: string;
  pageToken?: string;
  maxFiles?: number;
}

export interface BrowseConnectionFilesResponse {
  files: RemoteFile[];
  next_page_token: string | null;
  total_remote: number;
  total_ingested: number;
}

export const useBrowseConnectionFiles = (
  params: BrowseConnectionFilesParams,
  options?: Omit<
    UseQueryOptions<BrowseConnectionFilesResponse>,
    "queryKey" | "queryFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function fetchFiles(): Promise<BrowseConnectionFilesResponse> {
    const searchParams = new URLSearchParams();

    if (params.bucket) searchParams.set("bucket", params.bucket);
    if (params.search) searchParams.set("search", params.search);
    if (params.pageToken) searchParams.set("page_token", params.pageToken);
    if (params.maxFiles) searchParams.set("max_files", String(params.maxFiles));

    const url = `/api/connectors/${params.connectorType}/${params.connectionId}/browse?${searchParams.toString()}`;
    const response = await fetch(url);

    if (!response.ok) {
      const errorData = await response
        .json()
        .catch(() => ({ error: "Unknown error" }));
      throw new Error(
        errorData.error || `Failed to browse files: ${response.status}`,
      );
    }

    return response.json();
  }

  return useQuery(
    {
      queryKey: ["browseConnectionFiles", params],
      queryFn: fetchFiles,
      retry: false,
      enabled: Boolean(params.connectorType && params.connectionId),
      // Always reflect live ingestion state when the dialog opens. The global
      // default staleTime (60s) would otherwise serve a cached `is_ingested`
      // snapshot — e.g. a file deleted on the Knowledge page would still render
      // as "Ingested"/disabled here until the cache went stale. Matches the
      // bucket-status queries (useS3BucketStatusQuery / azure container-status).
      staleTime: 0,
      refetchOnMount: "always",
      ...options,
    },
    queryClient,
  );
};
