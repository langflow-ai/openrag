import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

export interface RevokeApiKeyRequest {
  key_id: string;
}

export interface RevokeApiKeyResponse {
  success: boolean;
}

export const useRevokeApiKeyMutation = (
  options?: Omit<
    UseMutationOptions<RevokeApiKeyResponse, Error, RevokeApiKeyRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function revokeApiKey(
    variables: RevokeApiKeyRequest,
  ): Promise<RevokeApiKeyResponse> {
    const response = await fetch(`/api/keys/${variables.key_id}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to revoke API key");
    }

    return response.json();
  }

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
