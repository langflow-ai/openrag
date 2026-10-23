import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface UploadHistogramParams {
  start: string;
  end: string;
  tz: string;
  connectorType?: string[];
  mimetype?: string[];
  owner?: string[];
  dataSources?: string[];
}

export interface UploadHistogram {
  /** Distinct files across all time, under the same non-date filters. */
  total: number;
  /** Distinct files uploaded per local day, keyed yyyy-MM-dd. */
  days: Record<string, number>;
}

export const useUploadHistogram = (
  params: UploadHistogramParams,
  options?: Omit<UseQueryOptions<UploadHistogram>, "queryKey" | "queryFn">,
) => {
  const queryClient = useQueryClient();

  async function fetchHistogram(): Promise<UploadHistogram> {
    const searchParams = new URLSearchParams({
      start: params.start,
      end: params.end,
      tz: params.tz,
    });
    for (const v of params.connectorType ?? [])
      searchParams.append("connector_type", v);
    for (const v of params.mimetype ?? []) searchParams.append("mimetype", v);
    for (const v of params.owner ?? []) searchParams.append("owner", v);
    for (const v of params.dataSources ?? [])
      searchParams.append("data_sources", v);

    const response = await apiClient.get(
      `/files/upload-histogram?${searchParams.toString()}`,
    );
    if (response.status < 200 || response.status >= 300) {
      throw new Error(
        response.data?.error ||
          `Failed to load upload histogram: ${response.status}`,
      );
    }
    return {
      total: response.data?.total ?? 0,
      days: response.data?.days ?? {},
    };
  }

  return useQuery(
    {
      queryKey: ["uploadHistogram", params],
      placeholderData: (prev: UploadHistogram | undefined) => prev,
      queryFn: fetchHistogram,
      retry: false,
      ...options,
    },
    queryClient,
  );
};
