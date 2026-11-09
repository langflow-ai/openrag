import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { EndpointType } from "@/contexts/chat-context";
import { apiClient } from "@/lib/api-client";

export interface BulkDeleteSessionsRequest {
  session_ids: string[];
  endpoint: EndpointType;
}

export interface BulkDeleteSessionsResponse {
  deleted: string[];
  failed: string[];
}

async function bulkDeleteSessions(
  variables: BulkDeleteSessionsRequest,
): Promise<BulkDeleteSessionsResponse> {
  const response = await apiClient.delete<BulkDeleteSessionsResponse>(
    "/sessions",
    {
      data: { session_ids: variables.session_ids },
    },
  );

  if (response.status < 200 || response.status >= 300) {
    const errorData = response.data as unknown as { error?: string };
    throw new Error(
      errorData.error || `Failed to delete sessions: ${response.status}`,
    );
  }

  return response.data;
}

export const useBulkDeleteSessionsMutation = (
  options?: Omit<
    UseMutationOptions<
      BulkDeleteSessionsResponse,
      Error,
      BulkDeleteSessionsRequest
    >,
    "mutationFn"
  >,
) => {
  const queryClient = useQueryClient();

  const { onSuccess, onError, onSettled, ...restOptions } = options ?? {};

  return useMutation({
    mutationFn: bulkDeleteSessions,
    ...restOptions,
    onSuccess: (...args) => {
      const [, variables] = args;
      queryClient.invalidateQueries({
        queryKey: ["conversations", variables.endpoint],
      });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      onSuccess?.(...args);
    },
    onError,
    onSettled,
  });
};
