import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface AzureBlobDefaults {
  connection_string_set: boolean;
  account_name: string;
  account_key_set: boolean;
  endpoint: string;
  auth_mode: "connection_string" | "account_key";
  container_names: string[];
  connection_id: string | null;
}

async function fetchAzureBlobDefaults(): Promise<AzureBlobDefaults> {
  const res = await apiClient.get<AzureBlobDefaults>(
    "/connectors/azure_blob/defaults",
  );
  if (res.status < 200 || res.status >= 300)
    throw new Error("Failed to fetch Azure Blob defaults");
  return res.data;
}

export function useAzureBlobDefaultsQuery(options?: { enabled?: boolean }) {
  return useQuery<AzureBlobDefaults>({
    queryKey: ["azure-blob-defaults"],
    queryFn: fetchAzureBlobDefaults,
    enabled: options?.enabled ?? true,
    staleTime: 0,
  });
}
