import {
  type UseQueryOptions,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { WebsiteSource } from "@/components/website-pages/types";

const PROCESSING_SOURCE_POLL_INTERVAL_MS = 2_000;

export const websiteSourceQueryKey = (sourceId: string) =>
  ["websiteSource", sourceId] as const;

async function getWebsiteSource(sourceId: string): Promise<WebsiteSource> {
  const response = await fetch(`/api/connectors/url/sources/${sourceId}`);
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as {
      detail?: string;
      error?: string;
    };
    throw new Error(
      data.detail || data.error || "Website source was not found",
    );
  }
  return response.json();
}

export function useGetWebsiteSourceQuery(
  sourceId: string,
  options?: Omit<UseQueryOptions<WebsiteSource, Error>, "queryKey" | "queryFn">,
) {
  const queryClient = useQueryClient();

  return useQuery(
    {
      queryKey: websiteSourceQueryKey(sourceId),
      queryFn: () => getWebsiteSource(sourceId),
      refetchInterval: (query) =>
        query.state.data?.status === "processing"
          ? PROCESSING_SOURCE_POLL_INTERVAL_MS
          : false,
      refetchIntervalInBackground: true,
      retry: false,
      ...options,
    },
    queryClient,
  );
}
