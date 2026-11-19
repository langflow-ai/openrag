import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotSource,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

export function useSnapshotSourcesQuery(enabled = true) {
  return useQuery({
    queryKey: snapshotKeys.sources,
    queryFn: async ({ signal }) => {
      const data = await snapshotRequest<{ sources?: SnapshotSource[] }>(
        "/sources",
        { signal, fallbackError: "Snapshot sources could not be loaded" },
      );
      return data.sources ?? [];
    },
    enabled,
    retry: false,
  });
}
