import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface IBMCOSDefaults {
  api_key_set: boolean;
  service_instance_id: string;
  endpoint: string;
  hmac_access_key_set: boolean;
  hmac_secret_key_set: boolean;
  auth_mode: "iam" | "hmac";
  bucket_names: string[];
  connection_id: string | null;
  disable_iam: boolean;
}

async function fetchIBMCOSDefaults(): Promise<IBMCOSDefaults> {
  const res = await apiClient.get<IBMCOSDefaults>(
    "/connectors/ibm_cos/defaults",
  );
  if (res.status < 200 || res.status >= 300)
    throw new Error("Failed to fetch IBM COS defaults");
  return res.data;
}

export function useIBMCOSDefaultsQuery(options?: { enabled?: boolean }) {
  return useQuery<IBMCOSDefaults>({
    queryKey: ["ibm-cos-defaults"],
    queryFn: fetchIBMCOSDefaults,
    enabled: options?.enabled ?? true,
    staleTime: 0,
  });
}
