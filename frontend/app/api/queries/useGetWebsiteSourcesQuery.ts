import { useQuery } from "@tanstack/react-query";
import type { WebsiteSource } from "@/components/website-pages/types";

export const websiteSourcesQueryKey = ["websiteSources"] as const;

async function getWebsiteSources(): Promise<WebsiteSource[]> {
  const response = await fetch("/api/connectors/url/sources");
  if (!response.ok) {
    throw new Error("Website sources could not be loaded");
  }
  const data = (await response.json()) as { sources?: WebsiteSource[] };
  return data.sources ?? [];
}

export function useGetWebsiteSourcesQuery(enabled: boolean) {
  return useQuery({
    queryKey: websiteSourcesQueryKey,
    queryFn: getWebsiteSources,
    enabled,
    retry: false,
  });
}
