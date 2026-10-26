import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface AzureBlobContainerStatus {
  name: string;
  ingested_count: number;
  is_synced: boolean;
}

async function fetchAzureBlobContainerStatus(
  connectionId: string,
): Promise<AzureBlobContainerStatus[]> {
  const res = await apiClient.get<{ containers: AzureBlobContainerStatus[] }>(
    `/connectors/azure_blob/${connectionId}/container-status`,
  );
  if (res.status < 200 || res.status >= 300) {
    const err = (res.data ?? {}) as { error?: string };
    throw new Error(err.error || "Failed to fetch container status");
  }
  return res.data.containers;
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
