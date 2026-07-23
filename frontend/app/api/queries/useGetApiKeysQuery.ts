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

async function getApiKeys(): Promise<GetApiKeysResponse> {
  const response = await fetch("/api/keys");
  if (response.ok) {
    return await response.json();
  }
  throw new Error("Failed to fetch API keys");
}

export const useGetApiKeysQuery = (
  options?: Omit<UseQueryOptions<GetApiKeysResponse>, "queryKey" | "queryFn">,
) => {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: getApiKeys,
    ...options,
  });
};
