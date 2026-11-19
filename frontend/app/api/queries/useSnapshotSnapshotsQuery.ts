import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotListing,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

/** Lists the snapshots in a source's S3 repository (reads the bucket). */
export function useSnapshotSnapshotsQuery(sourceId: string | null) {
  return useQuery({
    queryKey: snapshotKeys.snapshots(sourceId ?? ""),
    queryFn: ({ signal }) =>
      snapshotRequest<SnapshotListing>(`/sources/${sourceId}/snapshots`, {
        signal,
        fallbackError: "Snapshots could not be listed",
      }),
    enabled: !!sourceId,
    retry: false,
  });
}
