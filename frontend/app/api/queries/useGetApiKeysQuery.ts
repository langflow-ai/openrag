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

import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

export interface ApiKey {
  key_id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface GetApiKeysResponse {
  keys: ApiKey[];
}

export const useGetApiKeysQuery = (
  options?: Omit<UseQueryOptions<GetApiKeysResponse>, "queryKey" | "queryFn">,
) => {
  async function getApiKeys(): Promise<GetApiKeysResponse> {
    const response = await fetch("/api/keys");
    if (response.ok) {
      return await response.json();
    }
    throw new Error("Failed to fetch API keys");
  }

  return useQuery({
    queryKey: ["api-keys"],
    queryFn: getApiKeys,
    ...options,
  });
};
