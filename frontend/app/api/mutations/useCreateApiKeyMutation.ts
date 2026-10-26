import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";

export interface CreateApiKeyRequest {
  name: string;
}

export interface CreateApiKeyResponse {
  key_id: string;
  api_key: string;
  name: string;
  key_prefix: string;
  created_at: string;
}

async function createApiKey(
  variables: CreateApiKeyRequest,
): Promise<CreateApiKeyResponse> {
  const response = await apiClient.post<CreateApiKeyResponse>(
    "/keys",
    variables,
  );

  if (response.status < 200 || response.status >= 300) {
    const errorData = response.data as unknown as { error?: string };
    throw new Error(errorData.error || "Failed to create API key");
  }

  return response.data;
}

export const useCreateApiKeyMutation = (
  options?: Omit<
    UseMutationOptions<CreateApiKeyResponse, Error, CreateApiKeyRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: createApiKey,
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
