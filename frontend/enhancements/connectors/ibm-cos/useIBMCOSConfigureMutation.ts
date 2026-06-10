import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  bucketConnectorsConfiguredQueryFilter,
  connectorsQueryFilter,
} from "@/app/api/queries/useGetConnectorsQuery";

export interface IBMCOSConfigurePayload {
  auth_mode: "iam" | "hmac";
  endpoint: string;
  // IAM
  api_key?: string;
  service_instance_id?: string;
  auth_endpoint?: string;
  // HMAC
  hmac_access_key?: string;
  hmac_secret_key?: string;
  // Bucket selection
  bucket_names?: string[];
  // Updating an existing connection
  connection_id?: string;
}

async function configureIBMCOS(payload: IBMCOSConfigurePayload) {
  const res = await fetch("/api/connectors/ibm_cos/configure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Failed to configure IBM COS");
  return data as { connection_id: string; status: string };
}

export function useIBMCOSConfigureMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: configureIBMCOS,
    onSuccess: () => {
      queryClient.invalidateQueries(connectorsQueryFilter);
      queryClient.invalidateQueries({ queryKey: ["ibm-cos-defaults"] });
      queryClient.invalidateQueries(bucketConnectorsConfiguredQueryFilter);
    },
  });
}
