import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotImport,
  shouldPollImport,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

export const SNAPSHOT_POLL_INTERVAL_MS = 2000;

/** Own and shared imports; polls while any of them can still change on its own. */
export function useSnapshotImportsQuery(
  enabled = true,
  pollIntervalMs = SNAPSHOT_POLL_INTERVAL_MS,
) {
  return useQuery({
    queryKey: snapshotKeys.imports,
    queryFn: async ({ signal }) => {
      const data = await snapshotRequest<{ imports?: SnapshotImport[] }>(
        "/imports",
        { signal, fallbackError: "Snapshot imports could not be loaded" },
      );
      return data.imports ?? [];
    },
    enabled,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.some(shouldPollImport) ? pollIntervalMs : false,
  });
}
