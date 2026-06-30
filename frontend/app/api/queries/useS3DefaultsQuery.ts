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

export interface S3Defaults {
  access_key_set: boolean;
  secret_key_set: boolean;
  endpoint: string;
  region: string;
  bucket_names: string[];
  connection_id: string | null;
}

async function fetchS3Defaults(): Promise<S3Defaults> {
  const res = await fetch("/api/connectors/aws_s3/defaults");
  if (!res.ok) throw new Error("Failed to fetch S3 defaults");
  return res.json();
}

export function useS3DefaultsQuery(options?: { enabled?: boolean }) {
  return useQuery<S3Defaults>({
    queryKey: ["s3-defaults"],
    queryFn: fetchS3Defaults,
    enabled: options?.enabled ?? true,
    staleTime: 0,
  });
}
