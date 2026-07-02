import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface AzureBlobConfigurePayload {
  auth_mode: "connection_string" | "account_key";
  // connection_string mode
  connection_string?: string;
  // account_key mode
  account_name?: string;
  account_key?: string;
  endpoint?: string;
  // Container selection
  container_names?: string[];
  // Updating an existing connection
  connection_id?: string;
}

async function configureAzureBlob(payload: AzureBlobConfigurePayload) {
  const res = await fetch("/api/connectors/azure_blob/configure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Failed to configure Azure Blob");
  return data as { connection_id: string; status: string };
}

export function useAzureBlobConfigureMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: configureAzureBlob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["connectors"] });
      queryClient.invalidateQueries({ queryKey: ["azure-blob-defaults"] });
    },
  });
}
