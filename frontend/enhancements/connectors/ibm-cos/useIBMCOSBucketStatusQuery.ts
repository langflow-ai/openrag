import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface IBMCOSBucketStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchIBMCOSBucketStatus(
  connectionId: string,
): Promise<IBMCOSBucketStatus[]> {
  const res = await apiClient.get<{ buckets: IBMCOSBucketStatus[] }>(
    `/connectors/ibm_cos/${connectionId}/bucket-status`,
  );
  if (res.status < 200 || res.status >= 300) {
    const err = (res.data ?? {}) as { error?: string };
    throw new Error(err.error || "Failed to fetch bucket status");
  }
  return res.data.buckets;
}

export function useIBMCOSBucketStatusQuery(
  connectionId: string | null | undefined,
  options?: { enabled?: boolean },
) {
  return useQuery<IBMCOSBucketStatus[]>({
    queryKey: ["ibm-cos-bucket-status", connectionId],
    queryFn: () => fetchIBMCOSBucketStatus(connectionId!),
    enabled: (options?.enabled ?? true) && !!connectionId,
    staleTime: 0,
    refetchOnMount: "always",
  });
}
