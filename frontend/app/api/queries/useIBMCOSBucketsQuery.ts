import { useQuery } from "@tanstack/react-query";

async function fetchIBMCOSBuckets(connectionId: string): Promise<string[]> {
    const res = await fetch(`/api/connectors/ibm_cos/${connectionId}/buckets`);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Failed to list buckets");
    }
    const data = await res.json();
    return data.buckets as string[];
}

export function useIBMCOSBucketsQuery(
    connectionId: string | null | undefined,
    options?: { enabled?: boolean },
) {
    return useQuery<string[]>({
        queryKey: ["ibm-cos-buckets", connectionId],
        queryFn: () => fetchIBMCOSBuckets(connectionId!),
        enabled: (options?.enabled ?? true) && !!connectionId,
        staleTime: 30_000,
    });
}
