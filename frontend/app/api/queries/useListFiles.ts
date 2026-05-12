import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { File } from "./useGetSearchQuery";

export interface ListFilesParams {
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  connectorType?: string;
  mimetype?: string;
  owner?: string;
  search?: string;
}

export interface ListFilesResponse {
  files: File[];
  total: number;
  page: number;
  page_size: number;
}

export const useListFiles = (
  params: ListFilesParams = {},
  options?: Omit<UseQueryOptions<ListFilesResponse>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function fetchFiles(): Promise<ListFilesResponse> {
    const searchParams = new URLSearchParams();

    if (params.page) searchParams.set("page", String(params.page));
    if (params.pageSize) searchParams.set("page_size", String(params.pageSize));
    if (params.sortBy) searchParams.set("sort_by", params.sortBy);
    if (params.sortOrder) searchParams.set("sort_order", params.sortOrder);
    if (params.connectorType)
      searchParams.set("connector_type", params.connectorType);
    if (params.mimetype) searchParams.set("mimetype", params.mimetype);
    if (params.owner) searchParams.set("owner", params.owner);
    if (params.search) searchParams.set("search", params.search);

    const url = `/api/files?${searchParams.toString()}`;
    const response = await fetch(url);

    if (!response.ok) {
      const errorData = await response
        .json()
        .catch(() => ({ error: "Unknown error" }));
      throw new Error(
        errorData.error || `Failed to list files: ${response.status}`,
      );
    }

    const data = await response.json();

    // Map server response to File interface
    const files: File[] = (data.files || []).map(
      (f: Record<string, unknown>) => ({
        filename: (f.filename as string) || "",
        mimetype: (f.mimetype as string) || "",
        chunkCount: (f.chunk_count as number) || 0,
        source_url: (f.source_url as string) || "",
        owner: (f.owner as string) || "",
        owner_name: (f.owner_name as string) || "",
        owner_email: (f.owner_email as string) || "",
        size: (f.file_size as number) || 0,
        connector_type: (f.connector_type as string) || "local",
        embedding_model: f.embedding_model as string | undefined,
        embedding_dimensions: f.embedding_dimensions as number | undefined,
        allowed_users: (f.allowed_users as string[]) || [],
        allowed_groups: (f.allowed_groups as string[]) || [],
        status: "active" as const,
      }),
    );

    return {
      files,
      total: data.total || 0,
      page: data.page || 1,
      page_size: data.page_size || 25,
    };
  }

  return useQuery(
    {
      queryKey: ["listFiles", params],
      placeholderData: (prev: ListFilesResponse | undefined) => prev,
      queryFn: fetchFiles,
      retry: false,
      ...options,
    },
    queryClient,
  );
};
