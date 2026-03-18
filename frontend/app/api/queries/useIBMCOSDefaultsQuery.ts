import { useQuery } from "@tanstack/react-query";

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
    const res = await fetch("/api/connectors/ibm_cos/defaults");
    if (!res.ok) throw new Error("Failed to fetch IBM COS defaults");
    return res.json();
}

export function useIBMCOSDefaultsQuery(options?: { enabled?: boolean }) {
    return useQuery<IBMCOSDefaults>({
        queryKey: ["ibm-cos-defaults"],
        queryFn: fetchIBMCOSDefaults,
        enabled: options?.enabled ?? true,
        staleTime: 0,
    });
}
