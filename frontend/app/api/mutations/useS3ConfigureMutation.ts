import { useMutation, useQueryClient } from "@tanstack/react-query";

export interface S3ConfigurePayload {
    access_key?: string;
    secret_key?: string;
    endpoint_url?: string;
    region?: string;
    bucket_names?: string[];
    connection_id?: string;
}

async function configureS3(payload: S3ConfigurePayload) {
    const res = await fetch("/api/connectors/aws_s3/configure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to configure S3");
    return data as { connection_id: string; status: string };
}

export function useS3ConfigureMutation() {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: configureS3,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["connectors"] });
            queryClient.invalidateQueries({ queryKey: ["s3-defaults"] });
        },
    });
}
