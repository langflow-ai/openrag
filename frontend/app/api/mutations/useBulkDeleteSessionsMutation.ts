import {
  type UseMutationOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { EndpointType } from "@/contexts/chat-context";

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
  const response = await fetch("/api/sessions", {
    method: "DELETE",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ session_ids: variables.session_ids }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      errorData.error || `Failed to delete sessions: ${response.status}`,
    );
  }

  return response.json();
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
