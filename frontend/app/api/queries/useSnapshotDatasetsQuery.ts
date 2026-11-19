import { useQuery } from "@tanstack/react-query";
import {
  type SnapshotDatasetListing,
  snapshotKeys,
  snapshotRequest,
} from "@/lib/opensearch-snapshot";

/**
 * Datasets the caller may search (own + shared, active). The route is 404 when
 * the feature is off, so a failed request simply yields no datasets.
 */
export function useSnapshotDatasetsQuery(enabled = true) {
  return useQuery({
    queryKey: snapshotKeys.datasets,
    queryFn: async ({ signal }) => {
      const data = await snapshotRequest<{
        datasets?: SnapshotDatasetListing[];
      }>("/datasets", {
        signal,
        fallbackError: "Datasets could not be loaded",
      });
      return data.datasets ?? [];
    },
    enabled,
    retry: false,
  });
}
