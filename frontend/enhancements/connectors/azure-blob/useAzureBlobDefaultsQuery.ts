import { useQuery } from "@tanstack/react-query";

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
  const res = await fetch("/api/connectors/azure_blob/defaults");
  if (!res.ok) throw new Error("Failed to fetch Azure Blob defaults");
  return res.json();
}

export function useAzureBlobDefaultsQuery(options?: { enabled?: boolean }) {
  return useQuery<AzureBlobDefaults>({
    queryKey: ["azure-blob-defaults"],
    queryFn: fetchAzureBlobDefaults,
    enabled: options?.enabled ?? true,
    staleTime: 0,
  });
}
