import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotStatus,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

/** `GET /status` always answers 200; `enabled` says whether the feature is on. */
export function useSnapshotStatusQuery(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: snapshotKeys.status,
    queryFn: ({ signal }) =>
      snapshotRequest<SnapshotStatus>("/status", {
        signal,
        fallbackError: "OpenSearch snapshot import status could not be loaded",
      }),
    enabled: options.enabled ?? true,
    retry: false,
    staleTime: 30_000,
  });
}
