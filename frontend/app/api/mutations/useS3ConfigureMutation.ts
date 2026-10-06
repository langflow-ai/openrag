import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface S3ConfigurePayload {
  access_key?: string;
  secret_key?: string;
  endpoint_url?: string;
  region?: string;
  bucket_names?: string[];
  connection_id?: string;
}

async function configureS3(payload: S3ConfigurePayload) {
  const res = await apiClient.post<{ connection_id: string; status: string }>(
    "/connectors/aws_s3/configure",
    payload,
  );
  if (res.status < 200 || res.status >= 300) {
    throw new Error(
      (res.data as unknown as { error?: string }).error ||
        "Failed to configure S3",
    );
  }
  return res.data;
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
