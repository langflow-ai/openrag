import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface S3BucketStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchS3BucketStatus(
  connectionId: string,
): Promise<S3BucketStatus[]> {
  const res = await apiClient.get<{ buckets: S3BucketStatus[] }>(
    `/connectors/aws_s3/${connectionId}/bucket-status`,
  );
  if (res.status < 200 || res.status >= 300) {
    const err = (res.data ?? {}) as { error?: string };
    throw new Error(err.error || "Failed to fetch bucket status");
  }
  return res.data.buckets;
}

export function useS3BucketStatusQuery(
  connectionId: string | null | undefined,
  options?: { enabled?: boolean },
) {
  return useQuery<S3BucketStatus[]>({
    queryKey: ["s3-bucket-status", connectionId],
    queryFn: () => fetchS3BucketStatus(connectionId!),
    enabled: (options?.enabled ?? true) && !!connectionId,
    staleTime: 0,
    refetchOnMount: "always",
  });
}
