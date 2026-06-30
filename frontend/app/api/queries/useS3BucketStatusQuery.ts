/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import { useQuery } from "@tanstack/react-query";

export interface S3BucketStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchS3BucketStatus(
  connectionId: string,
): Promise<S3BucketStatus[]> {
  const res = await fetch(
    `/api/connectors/aws_s3/${connectionId}/bucket-status`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Failed to fetch bucket status");
  }
  const data = await res.json();
  return data.buckets as S3BucketStatus[];
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
