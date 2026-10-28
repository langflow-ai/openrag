import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface FailedIngestion {
  connector_type: string;
  file_id: string;
  filename: string | null;
  last_error: string | null;
  attempt_count: number;
  /** True once the retry budget is spent: bucket ingestion skips the file
   * until it changes at the source or is retried from the UI. */
  skipped: boolean;
  first_failed_at: string;
  last_failed_at: string;
}

export interface FailedIngestionsResponse {
  max_attempts: number;
  failures: FailedIngestion[];
}

export const FAILED_INGESTIONS_QUERY_KEY = ["failed-ingestions"] as const;

async function fetchFailedIngestions(): Promise<FailedIngestionsResponse> {
  const response = await apiClient.get<FailedIngestionsResponse>(
    "/connectors/failed-ingestions",
  );
  if (response.status < 200 || response.status >= 300) {
    const err = (response.data ?? {}) as unknown as { error?: string };
    throw new Error(err.error || "Failed to load failed documents");
  }
  return response.data;
}

export function useFailedIngestionsQuery(options?: { enabled?: boolean }) {
  return useQuery<FailedIngestionsResponse>({
    queryKey: FAILED_INGESTIONS_QUERY_KEY,
    queryFn: fetchFailedIngestions,
    enabled: options?.enabled ?? true,
    refetchOnWindowFocus: false,
  });
}
