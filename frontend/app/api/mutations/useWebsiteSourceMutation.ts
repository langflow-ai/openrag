import {
  type QueryClient,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { TASKS_QUERY_KEY } from "@/app/api/queries/useGetTasksQuery";
import { websiteSourceQueryKey } from "@/app/api/queries/useGetWebsiteSourceQuery";
import type { WebsiteSource } from "@/components/website-pages/types";

export interface CreateWebsiteSourceRequest {
  name: string;
  starting_url: string;
  scope: "path" | "page" | "site";
  allow_subdomains: boolean;
  additional_hosts: string[];
  include_paths: string[];
  exclude_paths: string[];
  max_pages: number;
  max_depth: number;
  max_downloaded_mb: number;
  max_crawl_minutes: number;
  change_detection: "normalized_content_hash" | "always_reingest";
  resync_behavior: "full" | "root";
  removed_page_behavior: "retain" | "delete";
}

export interface WebsiteSourceTaskResponse {
  last_task_id?: string;
  task_id?: string;
}

export interface WebsiteSourcePageRequest {
  sourceId: string;
  pageId?: string;
}

async function readError(response: Response, fallback: string) {
  const data = (await response.json().catch(() => ({}))) as {
    detail?: string;
    error?: string;
  };
  return data.detail || data.error || fallback;
}

async function createWebsiteSource(
  request: CreateWebsiteSourceRequest,
): Promise<WebsiteSource & WebsiteSourceTaskResponse> {
  const response = await fetch("/api/connectors/url/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(
      await readError(response, "Could not create website source"),
    );
  }
  return response.json();
}

async function syncWebsiteSource({
  sourceId,
  pageId,
}: WebsiteSourcePageRequest): Promise<WebsiteSourceTaskResponse> {
  const endpoint = pageId
    ? `/api/connectors/url/sources/${sourceId}/pages/${pageId}/sync`
    : `/api/connectors/url/sources/${sourceId}/sync`;
  const response = await fetch(endpoint, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not start website sync"));
  }
  return response.json();
}

async function deleteWebsiteSourcePage({
  sourceId,
  pageId,
}: WebsiteSourcePageRequest): Promise<void> {
  const endpoint = pageId
    ? `/api/connectors/url/sources/${sourceId}/pages/${pageId}`
    : `/api/connectors/url/sources/${sourceId}`;
  const response = await fetch(endpoint, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(
      await readError(response, "Could not delete website source"),
    );
  }
}

function invalidateWebsiteSourceQueries(
  queryClient: QueryClient,
  sourceId: string,
) {
  queryClient.invalidateQueries({ queryKey: websiteSourceQueryKey(sourceId) });
  queryClient.invalidateQueries({ queryKey: ["search"] });
  queryClient.invalidateQueries({ queryKey: [...TASKS_QUERY_KEY] });
}

export function useCreateWebsiteSourceMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createWebsiteSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["search"] });
      queryClient.invalidateQueries({ queryKey: ["listFiles"] });
      queryClient.invalidateQueries({ queryKey: [...TASKS_QUERY_KEY] });
    },
  });
}

export function useSyncWebsiteSourceMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: syncWebsiteSource,
    onSuccess: (_data, { sourceId }) => {
      invalidateWebsiteSourceQueries(queryClient, sourceId);
    },
  });
}

export function useDeleteWebsiteSourcePageMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteWebsiteSourcePage,
    onSuccess: (_data, { sourceId }) => {
      invalidateWebsiteSourceQueries(queryClient, sourceId);
    },
  });
}
