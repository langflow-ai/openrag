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
}

export interface BrowseConnectionFilesParams {
  connectorType: string;
  connectionId: string;
  bucket?: string;
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
      ...options,
    },
    queryClient,
  );
};
