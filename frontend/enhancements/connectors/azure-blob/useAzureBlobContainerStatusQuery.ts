import { useQuery } from "@tanstack/react-query";

export interface AzureBlobContainerStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchAzureBlobContainerStatus(
  connectionId: string,
): Promise<AzureBlobContainerStatus[]> {
  const res = await fetch(
    `/api/connectors/azure_blob/${connectionId}/container-status`,
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Failed to fetch container status");
  }
  const data = await res.json();
  return data.containers as AzureBlobContainerStatus[];
}

export function useAzureBlobContainerStatusQuery(
  connectionId: string | null | undefined,
  options?: { enabled?: boolean },
) {
  return useQuery<AzureBlobContainerStatus[]>({
    queryKey: ["azure-blob-container-status", connectionId],
    queryFn: () => fetchAzureBlobContainerStatus(connectionId!),
    enabled: (options?.enabled ?? true) && !!connectionId,
    staleTime: 0,
    refetchOnMount: "always",
  });
}
