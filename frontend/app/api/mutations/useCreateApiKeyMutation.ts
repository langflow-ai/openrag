/* ******************************************************************************
 * IBM Confidential
 *
 * OCO Source Materials
 *
 *  Copyright IBM Corp. 2026  All Rights Reserved.
 *
 * The source code for this program is not published or otherwise divested
 * of its trade secrets, irrespective of what has been deposited with
 * the U.S. Copyright Office.
 ****************************************************************************** */

import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

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

export const useCreateApiKeyMutation = (
  options?: Omit<
    UseMutationOptions<CreateApiKeyResponse, Error, CreateApiKeyRequest>,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  async function createApiKey(
    variables: CreateApiKeyRequest,
  ): Promise<CreateApiKeyResponse> {
    const response = await fetch("/api/keys", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(variables),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || "Failed to create API key");
    }

    return response.json();
  }

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
