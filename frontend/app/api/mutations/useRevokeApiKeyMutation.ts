import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface RevokeApiKeyRequest {
  key_id: string;
}

export interface RevokeApiKeyResponse {
  success: boolean;
}

async function revokeApiKey(
  variables: RevokeApiKeyRequest,
): Promise<RevokeApiKeyResponse> {
  const response = await apiClient.delete<RevokeApiKeyResponse>(
    `/keys/${variables.key_id}`,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorData = response.data as unknown as { error?: string };
    throw new Error(errorData.error || "Failed to revoke API key");
  }

  return response.data;
}

export const useRevokeApiKeyMutation = (
  options?: Omit<
    UseMutationOptions<RevokeApiKeyResponse, Error, RevokeApiKeyRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: revokeApiKey,
    onSuccess: (...args) => {
      queryClient.invalidateQueries({
        queryKey: ["api-keys"],
      });
      options?.onSuccess?.(...args);
    },
    onError: options?.onError,
    onSettled: options?.onSettled,
  });
};
