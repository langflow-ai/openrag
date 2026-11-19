import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotImport,
  shouldPollImport,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";
import { SNAPSHOT_POLL_INTERVAL_MS } from "./useSnapshotImportsQuery";

/** One import; polls until its job settles and no recovery is pending. */
export function useSnapshotImportQuery(
  importId: string | null,
  pollIntervalMs = SNAPSHOT_POLL_INTERVAL_MS,
) {
  return useQuery({
    queryKey: snapshotKeys.import(importId ?? ""),
    queryFn: ({ signal }) =>
      snapshotRequest<SnapshotImport>(`/imports/${importId}`, {
        signal,
        fallbackError: "Snapshot import could not be loaded",
      }),
    enabled: !!importId,
    retry: false,
    refetchInterval: (query) =>
      query.state.data && shouldPollImport(query.state.data)
        ? pollIntervalMs
        : false,
  });
}
