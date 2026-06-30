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

export interface IBMCOSBucketStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchIBMCOSBucketStatus(
  connectionId: string,
): Promise<IBMCOSBucketStatus[]> {
  const res = await fetch(
    `/api/connectors/ibm_cos/${connectionId}/bucket-status`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Failed to fetch bucket status");
  }
  const data = await res.json();
  return data.buckets as IBMCOSBucketStatus[];
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
